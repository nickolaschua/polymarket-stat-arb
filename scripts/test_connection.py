#!/usr/bin/env python3
"""Quick test script to verify API connectivity."""

import sys
sys.path.insert(0, ".")

from py_clob_client.client import ClobClient

def main():
    print("Testing Polymarket API connection...\n")
    
    client = ClobClient("https://clob.polymarket.com")
    
    # Test basic connectivity
    print("1. Testing /ok endpoint...")
    try:
        ok = client.get_ok()
        print(f"   ✓ Response: {ok}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
        return 1
    
    # Test server time
    print("\n2. Getting server time...")
    try:
        time = client.get_server_time()
        print(f"   ✓ Server time: {time}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test market fetch
    print("\n3. Fetching markets...")
    try:
        markets = client.get_simplified_markets()
        count = len(markets.get("data", []))
        print(f"   ✓ Found {count} markets")
        
        if count > 0:
            sample = markets["data"][0]
            print(f"   Sample: {sample.get('question', 'N/A')[:50]}...")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test price fetch (using a known active market if available)
    print("\n4. Testing price fetch...")
    try:
        markets_data = markets.get("data", [])
        if markets_data:
            # Find a market with token IDs
            for m in markets_data[:10]:
                tokens = m.get("clobTokenIds", "").split(",")
                if tokens and tokens[0]:
                    token_id = tokens[0].strip()
                    price = client.get_price(token_id, side="BUY")
                    mid = client.get_midpoint(token_id)
                    print(f"   ✓ Token {token_id[:20]}...")
                    print(f"     Price (buy): ${price}")
                    print(f"     Midpoint: ${mid}")
                    break
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "="*50)
    print("Connection test complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
