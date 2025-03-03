import React, { useEffect, useState, useRef } from "react";
import './styles/App.css';
import VideoPlayer from "./VideoPlayer";

function CameraStream() {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState(null);
  const videoRef = useRef(null);
  const peerConnectionRef = useRef(null);
  
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
                "stun:77.174.190.102:3478"
              ],
            },
            {
                urls: ["turn:77.174.190.102:5349"],
                username: "user",
                credential: "supersecretpassword",
                credentialType: "password",
                realm: "stream.lifeofarobin.com"
            }
          ]
        });

        pc.ontrack = (event) => {
          console.log('Received track:', event.track);
          if (videoRef.current && event.streams[0]) {
            videoRef.current.srcObject = event.streams[0];
            console.log('Set video source:', event.streams[0]);
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
        console.log(`client name: ${name} | Offer created: ${offer}`);
        const response = await fetch(`https://${process.env.REACT_APP_API_URL}:${process.env.REACT_APP_API_PORT}/webrtc/offer`, {
        // const response = await fetch(`http://localhost:8051/webrtc/offer`, {
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
      
        // Handle remote stream
        const remoteStream = peerConnectionRef.current.getRemoteStreams()[0];
        if (videoRef.current && remoteStream) {
          videoRef.current.srcObject = remoteStream;
          console.log('Remote stream:', remoteStream);
        } else {
          console.error('Failed to get remote stream');
        }
        
        console.log('Peer connection:', peerConnectionRef.current);

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
          // <VideoPlayer peerConnection={peerConnectionRef.current} />
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            className="chicken-viewport"
            style={{ width: '100%', height: '100%'}}>
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