import { createApp } from 'vue';
import App from './App.vue';
import { bridgeState, initBridge } from './bridge/qwebchannel';
import './styles/main.css';

initBridge();

createApp(App)
  .provide('bridgeState', bridgeState)
  .mount('#app');
