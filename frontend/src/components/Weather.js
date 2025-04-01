import React, { useState, useEffect } from 'react';
import '../styles/Weather.css';

function Weather() {
  const [weatherData, setWeatherData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchWeatherData = async () => {
    try {
      setLoading(true);
      // const response = await fetch('/weather');
      const protocol = window.location.protocol === "https:" ? "https" : "http";
      const response = await fetch(`${protocol}://cam.lifeofarobin.com/weather`);
      // const response = await fetch(`${protocol}://localhost:8000/weather`);
      
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

  if (loading) return <div className="weather-loading">Loading weather...</div>;
  if (error) return <div className="weather-error">{error}</div>;
  if (!weatherData) return null;

  const { main, weather, wind } = weatherData;
  
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
          <img className="humidity" src="/humidity_icon.svg" alt="humidty" />
          <span className="detail-value">{main.humidity}%</span>
        </div>
        <div className="weather-detail">
          <img className="wind-arrow" src="/down_arrow.svg" alt="wind" />
          <span className="detail-value">{Math.round(wind.speed * 3.6)} km/h</span>
        </div>
      </div>
    </div>
  );
}

export default Weather;
