<script>
  import { onMount } from 'svelte';
  import '../styles/Weather.css';
  import { getApiBaseUrl } from '../utils.js';
  import LoadingCircleDots from './LoadingCircleDots.svelte';

  export let onCityChange = () => {};

  let weatherData = null;
  let loading = true;
  let error = null;
  let trembleAngle = 0;

  async function fetchWeatherData() {
    try {
      loading = true;
      const response = await fetch(`${getApiBaseUrl(false)}/weather`);
      if (!response.ok) throw new Error('Weather data not available');
      const data = await response.json();
      if (data.data.name) onCityChange(data.data.name);
      window.data = data;
      weatherData = data;
      loading = false;
    } catch (err) {
      console.error('Error fetching weather data:', err);
      error = 'Could not load weather data';
      loading = false;
    }
  }

  onMount(() => {
    fetchWeatherData();
    const weatherInterval = setInterval(fetchWeatherData, 1800000);

    const trembleInterval = setInterval(() => {
      if (weatherData && Math.random() < 0.3) {
        trembleAngle = (Math.random() - 0.5) * 10;
      }
    }, 2000);

    return () => {
      clearInterval(weatherInterval);
      clearInterval(trembleInterval);
    };
  });

  $: rotationAngle = weatherData ? weatherData.data.wind.deg + trembleAngle : 0;
  $: isStrongWind = weatherData ? (weatherData.data.wind.speed * 3.6) > 15 : false;
</script>

{#if loading}
  <LoadingCircleDots small />
{:else if error}
  <div class="weather-error">{error}</div>
{:else if weatherData}
  {@const { main, weather, wind } = weatherData.data}
  <div class="weather-container">
    <div class="weather-details">
      <div class="weather-detail">
        <img
          src={`https://openweathermap.org/img/wn/${weather[0].icon}.png`}
          alt={weather[0].description}
          class="weather-icon"
        />
        <span class="weather-temp">{Math.round(main.temp)}°C</span>
      </div>
      <div class="weather-detail">
        <img class="humidity" src="/humidity_icon.svg" alt="humidity" />
        <span class="detail-value">{main.humidity}%</span>
      </div>
      <div class="weather-detail">
        <img
          class="wind-arrow"
          class:strong={isStrongWind}
          src="/wind_arrow.svg"
          style="transform: rotate({rotationAngle}deg); transition: transform 0.5s ease-in-out; --wind-deg: {wind.deg}deg"
          alt="wind"
        />
        <span class="value">{Math.round(wind.speed * 3.6)}</span>
        <span class="wind-detail-label">km/h</span>
      </div>
    </div>
  </div>
{/if}
