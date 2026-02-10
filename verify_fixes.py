import asyncio
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

try:
    from src.components.weather import get_weather
except ImportError as e:
    print(f"Failed to import weather component: {e}")
    get_weather = None

try:
    from src.components.video_stream import create_local_tracks
except ImportError as e:
    print(f"Failed to import video_stream component: {e}")
    create_local_tracks = None

async def test_weather():
    print("Testing Weather Component...")
    try:
        # Default Rotterdam coords
        lat, lon = 51.9225, 4.47917
        data = await get_weather(lat, lon, cache_expiration=0)
        print(f"Weather data received: {data['name']}, Temp: {data['main']['temp']}")
    except Exception as e:
        print(f"Weather test failed: {e}")

async def test_video():
    print("\nTesting Video Component...")
    try:
        audio, video = create_local_tracks(enable_audio=False)
        if video:
            print(f"Video track created: {video}")
            if sys.platform == 'win32':
                # Test reading a frame
                print("Attempting to read a frame...")
                frame = await video.recv()
                if frame:
                    print(f"Frame received! Size: {frame.width}x{frame.height}")
                else:
                    print("No frame received.")
                
                # Cleanup
                if hasattr(video, 'stop'):
                    video.stop()
            else:
                print("Skipping frame read on non-Windows for now (focusing on Windows fix).")
        else:
            print("Failed to create video track.")
    except Exception as e:
        print(f"Video test failed: {e}")

async def main():
    if get_weather:
        await test_weather()
    else:
        print("Skipping weather test due to import error.")
        
    if create_local_tracks:
        await test_video()
    else:
        print("Skipping video test due to import error.")

if __name__ == "__main__":
    asyncio.run(main())
