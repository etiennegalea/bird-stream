import React, { useEffect, useState, useRef, useCallback } from "react";
import './styles/App.css';
import ChatRoom from './components/ChatRoom';
import Weather from './components/Weather';
import { getApiBaseUrl } from './utils';
import { LoadingDots, LoadingCircle, LoadingCircleDots } from './components/Loading';


function CameraStream() {
  const [viewerCount, setViewerCount] = useState(0);
  const [videoSrc, setVideoSrc] = useState("");
  const [fps, setFps] = useState(0);
  const [isChatVisible, setIsChatVisible] = useState(true);
  const [hasUnreadMessages, setHasUnreadMessages] = useState(false);
  const videoRef = useRef(null);

  useEffect(() => {
    const ws = new WebSocket(`${getApiBaseUrl()}/stream`);

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

  // Handle new message notifications
  const handleNewMessage = useCallback(() => {
    if (!isChatVisible) {
      setHasUnreadMessages(true);
      console.log("New message received, setting hasUnreadMessages to true");
    }
  }, [isChatVisible]);

  const toggleChat = () => {
    setIsChatVisible(!isChatVisible);
    if (!isChatVisible) {
      // When opening chat, clear the notification
      setHasUnreadMessages(false);
      console.log("Chat opened, clearing hasUnreadMessages");
    }
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
          <div className="stream-viewport" onClick={toggleFullScreen}>
            {!videoSrc && <LoadingCircleDots />}
            {videoSrc && (
              <img
                ref={videoRef}
                src={videoSrc}
                alt="Camera Stream"
                className="stream-image"
              />
            )}
            {videoSrc && (
              <div className="fullscreen-hint">
                <span>Click to toggle fullscreen</span>
              </div>
            )}
          </div>
          <div className="stream-info">
            <div className="viewer-count">
              <img src="/viewers_icon.svg" alt="viewers" />
              <span>{viewerCount}</span>
            </div>
            <div className="weather-info">
              <Weather />
            </div>
            <div className="info-container">
              <span className="label">FPS</span>
              <span className="value">{fps}</span>
            </div>
          </div>
        </div>
        
        <button
          className={`chat-toggle-btn ${!isChatVisible ? 'chat-hidden' : ''}`}
          onClick={toggleChat}
          aria-label={isChatVisible ? "Hide chat" : "Show chat"}
        >
          <img src="/chat_icon.svg" alt="Chat Icon" />
          <span className={`notification-marker ${!hasUnreadMessages ? 'seen' : ''}`}></span>
        </button>
        
        <div className={`chat-section ${!isChatVisible ? 'chat-hidden' : ''}`}>
          <ChatRoom onNewMessage={handleNewMessage} />
        </div>
      </div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}
