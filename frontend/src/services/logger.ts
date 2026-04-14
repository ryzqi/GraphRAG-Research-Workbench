type LoggerMethod = (...args: unknown[]) => void;

function isDevelopment(): boolean {
  return process.env.NODE_ENV !== 'production';
}

function createDevOnlyLogger(method: LoggerMethod): LoggerMethod {
  return (...args: unknown[]) => {
    if (!isDevelopment()) {
      return;
    }
    method(...args);
  };
}

export const appLogger = {
  debug: createDevOnlyLogger((...args) => console.debug(...args)),
  info: createDevOnlyLogger((...args) => console.info(...args)),
  warn: (...args: unknown[]) => console.warn(...args),
  error: (...args: unknown[]) => console.error(...args),
};
