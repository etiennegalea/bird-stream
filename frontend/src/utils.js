/**
 * Utility functions for accessing environment variables and API endpoints
 */

/**
 * Get the base API URL based on the current environment
 * @param {boolean} ws - Whether to use WebSocket (default: false)
 * @returns {string} The base API URL
 */
export const getApiBaseUrl = (ws = false) => {
    // Determine the protocol based on request
    let protocol = '';
    if (ws) {
      protocol = window.location.protocol === "https:" ? "wss" : "ws";  
    } else {
      protocol = window.location.protocol === "https:" ? "https" : "http";
    }

    const baseURL = `${protocol}://${process.env.REACT_APP_API_URL}`;
    
    return baseURL;
  };

/**
 * Get the TURN server configuration with credentials from environment variables
 * @returns {Array} Array of TURN server configurations for RTCPeerConnection
 */
export const getTurnServers = () => {
  const username = process.env.REACT_APP_OPENRELAY_TURN_USERNAME;
  const credential = process.env.REACT_APP_OPENRELAY_TURN_CREDENTIAL;
  
  // Check if credentials are available
  if (!username || !credential) {
    console.warn('TURN server credentials not found in environment variables');
    return [];
  }
  
  return [
    {
      urls: [
        // "turn:global.relay.metered.ca:80",
        // "turn:global.relay.metered.ca:80?transport=tcp",
        "turn:global.relay.metered.ca:80?transport=udp",
        // "turn:global.relay.metered.ca:443",
        // "turns:/global.relay.metered.ca:443?transport=tcp",
        "turn:global.relay.metered.ca:443?transport=udp"
      ],
      username: username,
      credential: credential,
    },
  ];
};
