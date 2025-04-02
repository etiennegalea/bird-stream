import React, { useState, useEffect, useRef } from 'react';
import '../styles/Weather.css';
import { getApiBaseUrl } from '../utils';

function Weather() {
  const [weatherData, setWeatherData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [trembleAngle, setTrembleAngle] = useState(0);
  const windArrowRef = useRef(null);

  const fetchWeatherData = async () => {
    try {
      setLoading(true);

      const response = await fetch(`${getApiBaseUrl()}/weather`);
      
      if (!response.ok) {
        throw new Error('Weather data not available');
      }
      
      const data = await response.json();
      setWeatherData(data);
      setLoading(false);
    } catch (err) {
      console.error('Error fetching weather data:', err);
      setError('Could not load weather data');
      setLoading(false);
    }
  };

  useEffect(() => {
    // Fetch weather data immediately on component mount
    fetchWeatherData();
    
    // Set up polling every hour (3600000 ms)
    const intervalId = setInterval(fetchWeatherData, 3600000);
    
    // Clean up interval on component unmount
    return () => clearInterval(intervalId);
  }, []);

  // Add a function to create the trembling effect
  useEffect(() => {
    if (!weatherData) return;
    
    // Function to generate a random trembling angle
    const trembleArrow = () => {
      // Random angle between -5 and 5 degrees
      const randomAngle = (Math.random() - 0.5) * 10;
      setTrembleAngle(randomAngle);
    };
    
    // Set initial trembling
    trembleArrow();
    
    // Create random intervals for trembling
    const intervalId = setInterval(() => {
      // Only tremble sometimes (30% chance)
      if (Math.random() < 0.3) {
        trembleArrow();
      }
    }, 2000); // Check every 2 seconds
    
    return () => clearInterval(intervalId);
  }, [weatherData]);

  if (loading) return <div className="weather-loading">Loading weather...</div>;
  if (error) return <div className="weather-error">{error}</div>;
  if (!weatherData) return null;

  const { main, weather, wind } = weatherData;
  
  // Determine if the wind is strong (over 15 km/h)
  const isStrongWind = (wind.speed * 3.6) > 15;
  
  // Calculate the final rotation angle (base wind direction + trembling)
  const rotationAngle = wind.deg + trembleAngle;
  
  return (
    <div className="weather-container">
      <div className="weather-details">
        <div className="weather-detail">
          <img 
            src={`https://openweathermap.org/img/wn/${weather[0].icon}.png`} 
            alt={weather[0].description}
            className="weather-icon"
          />
          <span className="weather-temp">{Math.round(main.temp)}°C</span>
        </div>
        <div className="weather-detail">
          <img className="humidity" src="/humidity_icon.svg" alt="humidity" />
          <span className="detail-value">{main.humidity}%</span>
        </div>
        <div className="weather-detail">
          <img 
            ref={windArrowRef}
            className={`wind-arrow ${isStrongWind ? 'strong' : ''}`} 
            src="/wind_arrow.svg" 
            style={{
              transform: `rotate(${rotationAngle}deg)`,
              transition: 'transform 0.5s ease-in-out',
              '--wind-deg': `${wind.deg}deg`
            }}
            alt="wind" 
          />
          <span className="value">{Math.round(wind.speed * 3.6)}</span>
          <span className="wind-detail-label">km/h</span>
        </div>
      </div>
    </div>
  );
}

export default Weather;
