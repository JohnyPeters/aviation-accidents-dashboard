#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import time
import json
import os
import sys
from datetime import datetime, timezone
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

# Settings
INPUT_FILE = "data/crashes_data/plane_crash_data.csv"  # Input file name
CACHE_FILE = "data/crashes_data/coordinates_cache.csv"  # Coordinates cache file
LOG_FILE = "geocoding_log.txt"  # Log file
METADATA_FILE = "geocoding_metadata.json"  # Metadata file
# Nominatim requires a user agent that identifies the caller; override via env var.
USER_NAME = os.environ.get("GEOCODER_USER", "aviation-accidents-dashboard")
TIMESTAMP = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # UTC run timestamp
DELAY = 1.1  # Delay between API calls (seconds)

# Configure logging to file and console
import logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("GeocodingScript")

def geocode_location(location, geolocator, location_dict, attempts=3, delay=DELAY):
    """
    Geocodes a location with progressive word removal strategy.
    Attempts to remove words from the beginning until successfully geocoding.
    """
    if pd.isna(location) or location == "?":
        return None
    
    # Clean the location text
    location_clean = str(location).replace('"', '').strip()
    
    # Check if already in cache
    if location_clean in location_dict and location_dict[location_clean] not in [None, 'None']:
        # Convert tuple string to actual tuple if necessary
        if isinstance(location_dict[location_clean], str):
            coord_str = location_dict[location_clean].replace('(', '').replace(')', '')
            if ',' in coord_str:
                try:
                    lat, lon = map(float, coord_str.split(','))
                    return (lat, lon)
                except:
                    pass
        else:
            return location_dict[location_clean]
    
    # Create variations by removing words from the beginning
    location_variations = []
    
    # Add the original location
    location_variations.append(location_clean)
    
    # Split location into words
    words = location_clean.split()
    
    # Generate variations by removing words from the beginning (keeping at least 2 words)
    for i in range(1, len(words)-1):
        variation = ' '.join(words[i:])
        location_variations.append(variation)
    
    # If there is a comma, also try just the first main part
    if "," in location_clean:
        main_part = location_clean.split(",")[0].strip()
        words_main = main_part.split()
        for i in range(1, len(words_main)):
            variation = ' '.join(words_main[i:])
            if len(variation) > 3 and variation not in location_variations:
                location_variations.append(variation)
    
    # Try to geocode each variation
    for loc_variant in location_variations:
        logger.info(f"Attempting to geocode: '{loc_variant}' (variation of '{location_clean}')")
        
        for attempt in range(attempts):
            try:
                geocode_result = geolocator.geocode(loc_variant, exactly_one=True)
                if geocode_result:
                    coords = (geocode_result.latitude, geocode_result.longitude)
                    # Save to cache using the original location
                    location_dict[location_clean] = coords
                    logger.info(f"Success! '{loc_variant}' -> {coords}")
                    time.sleep(delay)
                    return coords
                time.sleep(delay)
            except (GeocoderTimedOut, GeocoderUnavailable) as e:
                logger.warning(f"Error in attempt {attempt+1} for '{loc_variant}': {str(e)}")
                time.sleep(delay * 2)
            except Exception as e:
                logger.error(f"Unexpected error in geocoding '{loc_variant}': {str(e)}")
                time.sleep(delay)
    
    logger.warning(f"Failed in all variations for '{location_clean}'")
    location_dict[location_clean] = None
    return None

def parse_route_with_stops(route):
    """Extracts all points from a route, including stopovers."""
    if pd.isna(route) or route == "?" or route in ["Demonstration", "Test flight", "Air show"]:
        return None
    
    # Remove quotes and clean
    route = str(route).replace('"', '').strip()
    
    # Check for slashes for alternative routes
    if '/' in route:
        # Take only the first mentioned route
        route = route.split('/')[0].strip()
    
    # Separate route points by hyphen
    waypoints = [point.strip() for point in route.split('-')]
    
    # Filter empty points
    waypoints = [wp for wp in waypoints if wp]
    
    # If there are at least two points, it's a valid route
    if len(waypoints) >= 2:
        return waypoints
    
    return None

def save_cache(location_dict, filename=CACHE_FILE):
    """Saves the cache dictionary to a CSV file."""
    logger.info(f"Saving cache with {len(location_dict)} locations to {filename}...")
    
    # Convert dictionary to DataFrame
    cache_df = pd.DataFrame({
        'Location': list(location_dict.keys()),
        'Coordinates': list(location_dict.values())
    })
    
    # Save to file
    cache_df.to_csv(filename, index=False)
    logger.info(f"Cache saved successfully!")

def main():
    # Record start time
    start_time = datetime.now()
    logger.info(f"=== Starting geocoding process at {start_time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    logger.info(f"User: {USER_NAME}")
    logger.info(f"Reference timestamp: {TIMESTAMP}")
    
    # Check if input file exists
    if not os.path.exists(INPUT_FILE):
        logger.error(f"ERROR: File {INPUT_FILE} not found!")
        return
    
    # Initialize geocoder
    user_agent = f"accident_map_geocoder_{USER_NAME.replace(' ', '_')}_{start_time.strftime('%Y%m%d')}"
    geolocator = Nominatim(user_agent=user_agent)
    logger.info(f"Geocoder initialized with user-agent: {user_agent}")
    
    # Load data
    logger.info(f"Loading data from {INPUT_FILE}...")
    df = pd.read_csv(INPUT_FILE)
    df = df.replace('?', np.nan)
    logger.info(f"Loaded {len(df)} accident records")
    
    # Check if we already have coordinates cache
    location_dict = {}
    if os.path.exists(CACHE_FILE):
        try:
            cache_df = pd.read_csv(CACHE_FILE)
            for _, row in cache_df.iterrows():
                location_dict[row['Location']] = row['Coordinates']
            logger.info(f"Cache loaded from {CACHE_FILE} with {len(location_dict)} locations")
        except Exception as e:
            logger.error(f"Error loading cache: {str(e)}")
            logger.info("Creating new cache...")
    
    # Geocode accident locations
    logger.info("Geocoding accident locations...")
    locations = []
    new_locations = False
    
    for i, location in enumerate(df['Location']):
        if i % 10 == 0 or i == len(df) - 1:
            logger.info(f"Progress: {i+1}/{len(df)} ({((i+1)/len(df)*100):.1f}%)")
        
        if pd.isna(location) or location == "?":
            locations.append(None)
            continue
            
        location_clean = str(location).replace('"', '').strip()
        
        if location_clean in location_dict and location_dict[location_clean] not in [None, 'None']:
            # Already in cache
            coords = location_dict[location_clean]
            if isinstance(coords, str):
                # Convert string to tuple if necessary
                coord_str = coords.replace('(', '').replace(')', '')
                if ',' in coord_str:
                    try:
                        lat, lon = map(float, coord_str.split(','))
                        locations.append((lat, lon))
                    except:
                        locations.append(None)
                else:
                    locations.append(None)
            else:
                locations.append(coords)
        else:
            # Geocode new location
            coords = geocode_location(location_clean, geolocator, location_dict)
            locations.append(coords)
            new_locations = True
        
        # Save cache every 20 items to prevent data loss
        if (i + 1) % 20 == 0 and new_locations:
            save_cache(location_dict)
    
    # Add coordinates to DataFrame
    df['Coordinates'] = locations
    
    # Process complete routes (including stopovers)
    logger.info("Processing routes (including stopovers)...")
    routes_info = []
    routes_with_stops = 0
    all_waypoints_count = 0
    
    for i, route in enumerate(df['Route']):
        if i % 10 == 0 or i == len(df) - 1:
            logger.info(f"Progress: {i+1}/{len(df)} ({((i+1)/len(df)*100):.1f}%)")
        
        # Extract all points from the route
        waypoints = parse_route_with_stops(route)
        
        if waypoints:
            # Count routes with stopovers
            if len(waypoints) > 2:
                routes_with_stops += 1
                logger.info(f"Route with stopovers ({len(waypoints)} points): {route}")
            
            all_waypoints_count += len(waypoints)
            
            # Geocode each route point
            waypoint_coords = []
            for point in waypoints:
                coords = geocode_location(point, geolocator, location_dict)
                waypoint_coords.append(coords)
                new_locations = True
            
            # Store route information
            routes_info.append({
                'origin': waypoints[0],
                'destination': waypoints[-1],
                'waypoints': waypoints,
                'waypoint_coords': waypoint_coords
            })
            
            # Save cache every 10 routes
            if (i + 1) % 10 == 0 and new_locations:
                save_cache(location_dict)
        else:
            routes_info.append(None)
    
    # Save final cache
    if new_locations:
        save_cache(location_dict)
    
    # Save metadata
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60.0  # in minutes
    
    metadata = {
        "process_start": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "process_end": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_minutes": round(duration, 2),
        "user": USER_NAME,
        "timestamp": TIMESTAMP,
        "total_accidents": len(df),
        "accidents_with_coordinates": sum(1 for loc in locations if loc is not None),
        "total_routes_processed": len(routes_info),
        "routes_with_waypoints": sum(1 for r in routes_info if r is not None),
        "routes_with_stops": routes_with_stops,
        "total_waypoints": all_waypoints_count,
        "unique_locations_geocoded": len(location_dict),
        "valid_locations_geocoded": sum(1 for loc in location_dict.values() if loc is not None),
    }
    
    with open(METADATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=4)
    
    logger.info(f"Metadata saved to {METADATA_FILE}")
    
    # Final statistics
    valid_locations = sum(1 for loc in location_dict.values() if loc is not None)
    logger.info(f"=== Process completed ===")
    logger.info(f"Total accidents: {len(df)}")
    logger.info(f"Accidents with coordinates: {sum(1 for loc in locations if loc is not None)} ({((sum(1 for loc in locations if loc is not None)/len(df))*100):.1f}%)")
    logger.info(f"Processed routes: {sum(1 for r in routes_info if r is not None)} of {len(df)}")
    logger.info(f"Routes with stopovers: {routes_with_stops}")
    logger.info(f"Total waypoints: {all_waypoints_count}")
    logger.info(f"Unique locations processed: {len(location_dict)}")
    logger.info(f"Valid locations: {valid_locations} ({(valid_locations/len(location_dict)*100):.1f}%)")
    logger.info(f"Total time: {(end_time - start_time).total_seconds() / 60.0:.2f} minutes")
    logger.info(f"Cache saved to: {CACHE_FILE}")
    logger.info(f"Complete log in: {LOG_FILE}")
    logger.info(f"Metadata in: {METADATA_FILE}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("Process interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())