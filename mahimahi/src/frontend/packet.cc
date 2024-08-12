const ETHERNET_HEADER_LEN = 14;

struct packet = {
    struct ethernet_header;
    struct ip_hdr;
    char* data; 
}

struct ethernet_header = {
    char*[ETHERNET_HEADER_LEN] hdr;
}

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

bool match_address(struct sockaddr_in src_addr, const char* contents, unsigned int content_length ){
    // struct packet* pkt = (struct packet*)malloc(sizeof(struct packet));

    // if (pkt == NULL) {
    //     return false;
    // }

    // const char* raw_bytes = contents.data();
    // size_t packet_len = contents.size();

    // if (bytes_available < sizeof(struct ethernet_header) + sizeof(struct ip_hdr)) {
    //     free(pkt);
    //     return false;
    // }

    // memcpy(&pkt->ethernet_header, raw_bytes, sizeof(struct ethernet_header));
    // memcpy(&pkt->ip_hdr, raw_bytes + sizeof(struct ethernet_header), sizeof(struct ip_hdr));

    // if(&pkt->ip_hdr.src_ip == src_ip){
    //     printf("yesss");
    // }

    return true;
}