import React, { useEffect, useRef, useState } from "react";

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0); // Optional viewer count
  const videoRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8051/ws/video"); // Update with your WebSocket URL

    ws.onmessage = (event) => {
      const frameData = event.data; // Base64 string
      if (videoRef.current) {
        videoRef.current.src = `data:image/jpeg;base64,${frameData}`; // Display frame
      }
    };

    ws.onclose = () => {
      console.log("WebSocket connection closed");
    };

    return () => ws.close(); // Cleanup WebSocket connection
  }, []);

  return (
    <div style={{ textAlign: "center" }}>
      <h1>Camera Stream</h1>
      <p>Viewers: {viewerCount}</p> {/* Optional viewer count */}
      <div style={{ border: "2px solid black", display: "inline-block" }}>
        <img ref={videoRef} alt="Camera Stream" style={{ width: "100%", height: "auto" }} />
      </div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
