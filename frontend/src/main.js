import './index.css';
import './styles/App.css';
import './appearance.js';
import App from './App.svelte';

const app = new App({
  target: document.getElementById('app')
});

export default app;
