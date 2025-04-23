#ifndef PACKET_ANALYZER_H
#define PACKET_ANALYZER_H

#include <stdint.h>     // For uint8_t, uint16_t, etc.
#include <string>       // For std::string
#include <netinet/in.h> // For struct sockaddr_in

// Constants
#define ETHERNET_HEADER_LEN 14

// Structure definitions
struct ethernet_header {
    char hdr[ETHERNET_HEADER_LEN];
};

struct ip_hdr {
    uint8_t  version_and_ihl;
    uint8_t  tos;
    uint16_t total_length;
    uint16_t identification;
    uint16_t flags_and_offset;
    uint8_t  ttl;
    uint8_t  protocol;
    uint16_t checksum;
    uint32_t src_ip;
    uint32_t dest_ip;
};

struct packet {
    struct ethernet_header ethernet_header;
    struct ip_hdr ip_hdr;
    char* data;
};

// Function prototype
bool match_address(struct sockaddr_in src_addr, const char* contents, unsigned int content_length);

#endif /* PACKET_ANALYZER_H */