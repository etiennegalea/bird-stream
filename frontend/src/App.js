import React, { useEffect, useState } from "react";
import './styles/App.css';

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);
  const [videoSrc, setVideoSrc] = useState("");
  const [fps, setFps] = useState(0);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    // const ws = new WebSocket(`${protocol}://${window.location.hostname}/stream`);
    const ws = new WebSocket(`${protocol}://cam.lifeofarobin.com/stream`);

    ws.onmessage = (event) => {
      const framedata = JSON.parse(event.data);
      if (framedata.type === "video") {
        // Update video stream
        setVideoSrc(`data:image/jpeg;base64,${framedata.frame}`);
        setFps(Math.round(framedata.fps)); // Round FPS to 2 decimal places
        // Update viewer count
        setViewerCount(framedata.viewers);
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
      <p>FPS: {fps}</p>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
