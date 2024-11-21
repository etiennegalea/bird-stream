import React, { useEffect, useState } from "react";

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);
  const [videoSrc, setVideoSrc] = useState("");

  useEffect(() => {
    const ws = new WebSocket("ws://192.168.1.140:8051/ws/video");

    ws.onmessage = (event) => {
      console.log(event);
      const framedata = JSON.parse(event.data);
      if (framedata.type === "video") {
        // Update video stream
        console.log("video -- ", framedata)
        setVideoSrc(`data:image/jpeg;base64,${framedata.frame}`);
      } else if (framedata.type === "viewerCount") {
        // Update viewer count
        console.log("viewerCount -- ", framedata)
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
    <div style={{ textAlign: "center" }}>
      <h1>Camera Stream</h1>
      <p>Viewers: {viewerCount}</p> {/* Display viewer count */}
      <div style={{ border: "2px solid black", display: "inline-block" }}>
        {/* Use videoSrc for the <img> src attribute */}
        <img src={videoSrc} alt="Camera Stream" style={{ width: "100%", height: "auto" }} />
      </div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
