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
    console.log(baseURL)
    
    return baseURL;
  };