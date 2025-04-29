import React, { useEffect, useState, useRef, useCallback } from "react";
import './styles/App.css';
import ChatRoom from './components/ChatRoom';
import Weather from './components/Weather';
import { getApiBaseUrl, getTurnServers } from './utils';
import { LoadingDots, LoadingCircle, LoadingCircleDots } from './components/Loading';
import VideoPlayer from "./VideoPlayer";

function CameraStream() {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const [isChatVisible, setIsChatVisible] = useState(true);
  const [hasUnreadMessages, setHasUnreadMessages] = useState(false);
  const peerConnectionRef = useRef(null);
  const videoRef = useRef(null);
  
  useEffect(() => {
    const cleanup = () => {
      if (peerConnectionRef.current) {
        peerConnectionRef.current.close();
        peerConnectionRef.current = null;
      }
      if (videoRef.current) {
        videoRef.current.srcObject = null;
      }
    };

    const startStream = async () => {
      cleanup();

      try {
        const pc = new RTCPeerConnection({
          iceServers: [
            {
              urls: [
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
                "stun:stun2.l.google.com:19302",
                "stun:stun3.l.google.com:19302",
                "stun:stun4.l.google.com:19302"
              ],
            },
            ...getTurnServers()
          ],
          iceTransportPolicy: "relay",
          bundlePolicy: "max-bundle",
          rtcpMuxPolicy: "require"
        });

        // Filter out IPv6 candidates
        pc.onicecandidate = (event) => {
          if (event.candidate) {
            // Only keep IPv4 candidates
            if (event.candidate.candidate.indexOf('udp') !== -1 && 
                event.candidate.candidate.indexOf(':') !== -1 && 
                event.candidate.candidate.indexOf('::') === -1) {
              console.log('Using IPv4 candidate:', event.candidate.candidate);
            } else {
              console.log('Ignoring non-IPv4 candidate:', event.candidate.candidate);
            }
          }
        };

        pc.ontrack = (event) => {
          if (videoRef.current && event.streams[0]) {
            videoRef.current.srcObject = event.streams[0];
          }
        };
        peerConnectionRef.current = pc;

        // Handle connection state changes
        pc.onconnectionstatechange = (event) => {
          switch(pc.connectionState) {
            case "connected":
              setIsConnected(true);
              break;
            case "disconnected":
            case "failed":
              setIsConnected(false);
              setError("Connection lost. Please refresh to try again.");
              break;
            default:
              break;
          }
        };

        // Create offer
        const offer = await pc.createOffer({
          offerToReceiveVideo: true,
          offerToReceiveAudio: false,
        });
        await pc.setLocalDescription(offer);

        const name = getRandomName();

        // Send offer to server
        // console.log(`client name: ${name} | Offer created: ${offer}`);
        // const response = await fetch(`https://${process.env.REACT_APP_API_URL}:${process.env.REACT_APP_API_PORT}/webrtc/offer`, {
        // const response = await fetch(`http://localhost:8051/webrtc/offer`, {
        // const response = await fetch(`http://127.0.0.1:8000/webrtc/offer`, {
        const response = await fetch(`${getApiBaseUrl()}/webrtc/offer`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            id: name,
            offer: {type: offer.type, sdp: offer.sdp}
          })
        });

        if (!response.ok) {
          throw new Error('Failed to connect to server');
        }

        // console.log('Response from server:', response);

        const answerData = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answerData));

        // console.log('Answer received:', answerData);
      
        // Handle remote stream
        const remoteStream = peerConnectionRef.current.getRemoteStreams()[0];
        if (videoRef.current && remoteStream) {
          videoRef.current.srcObject = remoteStream;
          // console.log('Remote stream:', remoteStream);
        } else {
          console.error('Failed to get remote stream');
        }
        
        // console.log('Peer connection:', peerConnectionRef.current);

      } catch (err) {
        console.error('Error setting up WebRTC:', err);
        setError('Failed to connect to camera stream. Please refresh to try again.');
      }
    };

    startStream();
    return cleanup;
  }, []);
  
  function getRandomName(prefix="client_") {
    return prefix + Math.random().toString(36).substring(2, 15);
  }

  // Handle new message notifications
  const handleNewMessage = useCallback(() => {
    if (!isChatVisible) {
      setHasUnreadMessages(true);
      // console.log("New message received, setting hasUnreadMessages to true");
    }
  }, [isChatVisible]);

  const toggleChat = () => {
    setIsChatVisible(!isChatVisible);
    if (!isChatVisible) {
      // When opening chat, clear the notification
      setHasUnreadMessages(false);
      // console.log("Chat opened, clearing hasUnreadMessages");
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
            {!isConnected && !error && <LoadingCircleDots />}
          {error ? (
            <div className="error-message">{error}</div>
          ) : (
          // <VideoPlayer peerConnection={peerConnectionRef.current} />
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="stream-viewport"
            style={{ width: '100%', height: '100%'}}>
            <track kind="captions" label="Captions" />
          </video>
        )}
        {isConnected && (
          <div className="fullscreen-hint">
            <span>Click to toggle fullscreen</span>
          </div>
        )}
      </div>
          <div className="stream-info">
            <div className="viewer-count">
              <img src="/viewers_icon.svg" alt="viewers" />
              {/* <span>{viewerCount}</span> */}
            </div>
            <div className="weather-info">
              <Weather />
            </div>
            <div className="connection-status">
              {isConnected ? '🟢' : '🔴'}
            </div>

            {/* <div className="info-container">
              <span className="label">FPS</span>
              <span className="value">{fps}</span>
            </div> */}
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