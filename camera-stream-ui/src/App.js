import React, { useEffect, useState } from 'react';

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);

  useEffect(() => {
    const ws = new WebSocket("ws://cam.lifeofarobin.com/ws");

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setViewerCount(data.viewer_count); // Update viewer count
    };

    ws.onclose = () => {
      console.log("WebSocket connection closed");
    };

    return () => ws.close();
  }, []);

  return (
    <div style={{ textAlign: 'center' }}>
      <h1>Camera Stream</h1>
      <p>Viewers: {viewerCount}</p>
      <div style={{ display: 'inline-block' }}>
        <img
          src="https://cam.lifeofarobin.com/stream"
          alt="Camera Stream"
          style={{ width: '100%', height: 'auto' }}
        />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div>
      <CameraStream />
    </div>
  );
}