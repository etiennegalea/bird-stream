import React, { useEffect, useState, useRef } from "react";
import './styles/App.css';

function CameraStream() {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const videoRef = useRef(null);
  const peerConnectionRef = useRef(null);

  const iceServers = {
    urls: [
      "stun:stun.l.google.com:19302",
      "stun:stun.l.google.com:5349"
    ]
  };
  
  useEffect(() => {
    const startStream = async () => {
      try {
        const pc = new RTCPeerConnection(iceServers);
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
        console.log(`client name: ${name} | Offer created: ${offer}`);
        const response = await fetch(`https://${process.env.REACT_APP_API_URL}:${process.env.REACT_APP_API_PORT}/webrtc/offer`, {
        // const response = await fetch(`http://127.0.0.1:8000/webrtc/offer`, {
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

        console.log('Response from server:', response);

        const answerData = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answerData));

        console.log('Answer received:', answerData);
      
        const remoteStream = peerConnectionRef.current.getRemoteStreams()[0];
        if (videoRef.current && remoteStream) {
          videoRef.current.srcObject = remoteStream;
        }

        console.log('Remote stream:', remoteStream);

      } catch (err) {
        console.error('Error setting up WebRTC:', err);
        setError('Failed to connect to camera stream. Please refresh to try again.');
      }
    };

    startStream();
  });
  
  function getRandomName(prefix="client_") {
    return prefix + Math.random().toString(36).substring(2, 15);
  }
  

  return (
    <div className="stream-container">
      <div className="header">
        <h1>BIRB STREAM</h1>
        <p>Bringing you beautiful Rotterdam birbs live!</p>
      </div>
      <div className="chicken-viewport">
        {error ? (
          <div className="error-message">{error}</div>
        ) : (
          <video ref={videoRef} autoPlay playsInline className="chicken-viewport">
            <track kind="captions" label="Captions" />
          </video>
        )}
      </div>
      <div className="connection-status">
        Status: {isConnected ? '🟢 Connected' : '🔴 Disconnected'}
      </div>
    </div>
  );
}

export default function App() {
  return <CameraStream />;
}