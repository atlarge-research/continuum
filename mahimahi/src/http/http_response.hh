/* -*-mode:c++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*- */

#ifndef HTTP_RESPONSE_HH
#define HTTP_RESPONSE_HH

#include <memory>

#include "http_message.hh"
#include "body_parser.hh"
#include "http_request.hh"

class HTTPResponse : public HTTPMessage
{
private:
    std::string status_code( void ) const;

    HTTPRequest request_ {};

    /* required methods */
    void calculate_expected_body_size( void ) override;
    size_t read_in_complex_body( const std::string & str ) override;
    bool eof_in_body( void ) const override;

    std::unique_ptr< BodyParser > body_parser_ { nullptr };

public:
    void set_request( const HTTPRequest & request );
    const HTTPRequest & request( void ) const { return request_; }

    using HTTPMessage::HTTPMessage;
};

#endif /* HTTP_RESPONSE_HH */
