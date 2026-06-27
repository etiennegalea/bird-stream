<script>
  import '../styles/loading/LoadingCircleDots.css';

  export let small = false;
  export let className = '';
</script>

<div class="loading-container {className}">
  <div class="loading-circle" class:small>
    <div class="loading-circle-dot"></div>
    <div class="loading-circle-dot"></div>
    <div class="loading-circle-dot"></div>
    <div class="loading-circle-dot"></div>
  </div>
</div>
