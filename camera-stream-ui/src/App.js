import React from 'react';

function CameraStream() {
  return (
    <div style={{ textAlign: 'center' }}>
      <h1>Birb Stream</h1>
      <div style={{ border: '2px solid black', display: 'inline-block' }}>
        {/* Display the camera stream */}
        <img
          src="http://localhost:8051/stream"
          alt="Birb Stream"
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
