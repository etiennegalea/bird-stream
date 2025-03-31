import React, { useEffect, useState, useRef } from "react";
import './styles/App.css';
import ChatRoom from './components/ChatRoom';

function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);
  const [videoSrc, setVideoSrc] = useState("");
  const [fps, setFps] = useState(0);
  const [isChatVisible, setIsChatVisible] = useState(true);
  const videoRef = useRef(null);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    // const ws = new WebSocket(`${protocol}://cam.lifeofarobin.com/stream`);
    const ws = new WebSocket(`${protocol}://localhost:8000/stream`);

    ws.onmessage = (event) => {
      const framedata = JSON.parse(event.data);
      // Update video stream
      setVideoSrc(`data:image/jpeg;base64,${framedata.frame}`);
      setFps(Math.round(framedata.fps)); // Round FPS to 2 decimal places
      // Update viewer count
      setViewerCount(framedata.viewers);
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    ws.onclose = () => {
      console.log("WebSocket connection closed");
    };
    
    return () => ws.close(); // Cleanup WebSocket on component unmount
  }, []);

  const toggleChat = () => {
    setIsChatVisible(!isChatVisible);
  };

  const toggleFullScreen = () => {
    const videoElement = videoRef.current;
    
    if (!videoElement) return;
    
    if (!document.fullscreenElement) {
      // Enter fullscreen
      if (videoElement.requestFullscreen) {
        videoElement.requestFullscreen();
      } else if (videoElement.webkitRequestFullscreen) { /* Safari */
        videoElement.webkitRequestFullscreen();
      } else if (videoElement.msRequestFullscreen) { /* IE11 */
        videoElement.msRequestFullscreen();
      }
    } else {
      // Exit fullscreen
      if (document.exitFullscreen) {
        document.exitFullscreen();
      } else if (document.webkitExitFullscreen) { /* Safari */
        document.webkitExitFullscreen();
      } else if (document.msExitFullscreen) { /* IE11 */
        document.msExitFullscreen();
      }
    }
  };

  return (
    <div className="app-container">
      <div className="header">
        <h1>BIRB STREAM</h1>
        <p>Bringing you beautiful Rotterdam birbs live!</p>
      </div>
      
      <div className={`main-content ${!isChatVisible ? 'chat-hidden' : ''}`}>
        <div className="stream-section">
          <div className="chicken-viewport" onClick={toggleFullScreen}>
            <img 
              ref={videoRef} 
              src={videoSrc} 
              alt="Camera Stream" 
              className="stream-image"
            />
            <div className="fullscreen-hint">
              <span>Click to toggle fullscreen</span>
            </div>
          </div>
          <div className="stream-info">
            <div className="viewer-count">👥 Viewers: {viewerCount}</div>
            <p>FPS: {fps}</p>
          </div>
        </div>
        
        <button 
          className={`chat-toggle-btn ${!isChatVisible ? 'chat-hidden' : ''}`}
          onClick={toggleChat}
          aria-label={isChatVisible ? "Hide chat" : "Show chat"}
        >
          {isChatVisible ? '→' : '←'}
        </button>
        
        <div className={`chat-section ${!isChatVisible ? 'chat-hidden' : ''}`}>
          <ChatRoom />
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
