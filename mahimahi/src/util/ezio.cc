/* -*-mode:c++; tab-width: 4; indent-tabs-mode: nil; c-basic-offset: 4 -*- */

#include <unistd.h>
#include <cassert>

#include "ezio.hh"
#include "exception.hh"

using namespace std;

long int myatoi( const string & str, const int base )
{
    if ( str.empty() ) {
        throw runtime_error( "Invalid integer string: empty" );
    }

    char *end;

    errno = 0;
    long int ret = strtol( str.c_str(), &end, base );

    if ( errno != 0 ) {
        throw unix_error( "strtol" );
    } else if ( end != str.c_str() + str.size() ) {
        throw runtime_error( "Invalid integer: " + str );
    }

    return ret;
}

double myatof( const string & str )
{
    if ( str.empty() ) {
        throw runtime_error( "Invalid floating-point string: empty" );
    }

    char *end;

    errno = 0;
    double ret = strtod( str.c_str(), &end );

    if ( errno != 0 ) {
        throw unix_error( "strtod" );
    } else if ( end != str.c_str() + str.size() ) {
        throw runtime_error( "Invalid floating-point number: " + str );
    }

    return ret;
}
