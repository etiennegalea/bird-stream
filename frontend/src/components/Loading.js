import React from 'react';
// import '../styles/loading/LoadingCircle.css';
// import '../styles/loading/LoadingDots.css';
import '../styles/loading/LoadingCircleDots.css';

export function LoadingDots({ small = false, className = '' }) {
  return (
    <div className={`loading-animation ${small ? 'small' : ''} ${className}`}>
      <div className="loading-dot loading-dot-1"></div>
      <div className="loading-dot loading-dot-2"></div>
      <div className="loading-dot loading-dot-3"></div>
      <div className="loading-dot loading-dot-4"></div>
    </div>
  );
}

export function LoadingCircle({ small = false, className = '' }) {
    return (
      <div className={`loading-container ${className}`}>
        <div className={`loading-spinner ${small ? 'small' : ''}`}>
          <div></div>
          <div></div>
          <div></div>
          <div></div>
        </div>
      </div>
    );
  }

export function LoadingCircleDots({ small = false, className = '' }) {
    return (
      <div className={`loading-container ${className}`}>
        <div className={`loading-circle ${small ? 'small' : ''}`}>
          <div className="loading-circle-dot"></div>
          <div className="loading-circle-dot"></div>
          <div className="loading-circle-dot"></div>
          <div className="loading-circle-dot"></div>
        </div>
      </div>
    );
  }