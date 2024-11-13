import React from 'react';

function CameraStream() {
  return (
    <div style={{ textAlign: 'center' }}>
      <h1>Birb Stream</h1>
      <div style={{ border: '2px solid black', display: 'inline-block' }}>
        {/* Display the camera stream */}
        <img
          src="https://cam.lifeofarobin.com/stream"
          alt="Birb Stream"
          style={{ width: '100%', height: 'auto' }}
        />
        {/* <video autoPlay muted loop>
          <source src="https://cam.lifeofarobin.com/stream" type="video/mp4" />
          Your browser does not support the video tag.
        </video> */}

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
