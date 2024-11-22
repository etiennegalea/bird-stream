import React, { useEffect, useState } from "react";
import './styles/App.css';

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);
  const [videoSrc, setVideoSrc] = useState("");

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    // const ws = new WebSocket(`${protocol}://${window.location.hostname}:8051/ws/video`);
    const ws = new WebSocket(`${protocol}://cam.lifeofarobin.com:8051/ws/video`);

    ws.onmessage = (event) => {
      const framedata = JSON.parse(event.data);
      if (framedata.type === "video") {
        // Update video stream
        setVideoSrc(`data:image/jpeg;base64,${framedata.frame}`);
      } else if (framedata.type === "viewerCount") {
        // Update viewer count
        setViewerCount(framedata.count);
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("WebSocket connection closed");
    };

    return () => ws.close(); // Cleanup WebSocket on component unmount
  }, []);

  return (
    <div className="stream-container">
      <div className="header">
        <h1>BIRB STREAM</h1>
        <p>Bringing you beautiful Rotterdam birbs live!</p>
      </div>
      <div className="chicken-viewport">
        {/* <img src="/chicken.jpg" alt="Chicken Stream" /> */}
        <img src={videoSrc} alt="Camera Stream" className="chicken-viewport" />
      </div>
      <div className="viewer-count">👥 Viewers: {viewerCount}</div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
