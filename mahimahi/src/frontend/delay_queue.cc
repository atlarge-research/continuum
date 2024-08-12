/* -*-mode:c++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*- */

#include <limits>

#include "delay_queue.hh"
#include "timestamp.hh"
#include <iostream>
#include <string>
#include <cstring>
#include <netinet/in.h> 
#include <arpa/inet.h> 

using namespace std;

const size_t ETHERNET_HEADER_LEN = 16;

struct ethernet_header {
    char hdr [ETHERNET_HEADER_LEN];
} __attribute__((packed));

struct ip_hdr {
    uint32_t src_ip;
    uint32_t dest_ip;
} __attribute__((packed));


struct packet {
    struct ethernet_header eth_hdr;
    struct ip_hdr ip_hdr;
    char* data; 
} __attribute__((packed));

bool match_address(char* src_ip, char* dst_ip, const string & contents ){
    /*
        This function checks whether the packet matches ips from the src ips and dst ips.
        Returns true if it matches one of the arrays
    */

    // Checking for the source ip

    struct packet* pkt = (struct packet*)malloc(sizeof(struct packet));

    if (pkt == NULL) {
        return false;
    }

    const char* raw_bytes = contents.data();
    size_t packet_len = contents.size();

    if (packet_len < sizeof(struct ethernet_header) + sizeof(struct ip_hdr)) {
        free(pkt);
        return false;
    }

    memcpy(&pkt->eth_hdr, raw_bytes, sizeof(struct ethernet_header));
    memcpy(&pkt->ip_hdr, raw_bytes + sizeof(struct ethernet_header), sizeof(struct ip_hdr));

    if(src_ip != NULL){
        struct sockaddr_in src_addr;
        memset(&src_addr, 0, sizeof(src_addr));

        src_addr.sin_family = AF_INET;

        if (inet_pton(AF_INET, src_ip , &src_addr.sin_addr) <= 0) {
            return false;
        }

        uint32_t src_ip_int = src_addr.sin_addr.s_addr;

        if(pkt->ip_hdr.src_ip == src_ip_int){
            return true;
        }
    }

    if(dst_ip != NULL){
        struct sockaddr_in dest_addr;
        memset(&dest_addr, 0, sizeof(dest_addr));

        dest_addr.sin_family = AF_INET;

        if (inet_pton(AF_INET, dst_ip , &dest_addr.sin_addr) <= 0) {
            return false;
        }

        uint32_t dest_ip_int = dest_addr.sin_addr.s_addr;

        if(pkt->ip_hdr.dest_ip == dest_ip_int){
            return true;
        }
    }

    return false;
}

void DelayQueue::read_packet( const string & contents )
{
    if(match_address(getenv("SRC_TO_IGNORE"), getenv("DEST_TO_IGNORE"), contents)){
        // this is used to bypass mahimahi delays
        packet_queue_.emplace( timestamp(), contents );
        
        return;
    } 
    
    packet_queue_.emplace( timestamp() + delay_ms_, contents );
}

void DelayQueue::write_packets( FileDescriptor & fd )
{
    while ( (!packet_queue_.empty())
            && (packet_queue_.front().first <= timestamp()) ) {
        fd.write( packet_queue_.front().second );
        packet_queue_.pop();
    }
}

unsigned int DelayQueue::wait_time( void ) const
{
    if ( packet_queue_.empty() ) {
        return numeric_limits<uint16_t>::max();
    }

    const auto now = timestamp();

    if ( packet_queue_.front().first <= now ) {
        return 0;
    } else {
        return packet_queue_.front().first - now;
    }
}
