export const DEVICE_TEMP_HOT_C = 65;
export const DEVICE_TEMP_WARNING_C = 80;

export function temperatureState(value) {
  const celsius = Number(value);
  if (!Number.isFinite(celsius)) return null;
  if (celsius >= DEVICE_TEMP_WARNING_C) {
    return {
      level: 'warning',
      label: 'Too hot',
      description: 'Too hot — cooling or reduced workload recommended',
    };
  }
  if (celsius >= DEVICE_TEMP_HOT_C) {
    return {
      level: 'hot',
      label: 'Hot',
      description: 'Hot, but still within the acceptable range',
    };
  }
  return {
    level: 'normal',
    label: 'Normal',
    description: 'Good / normal temperature',
  };
}
