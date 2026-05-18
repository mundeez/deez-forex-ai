import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "";

export const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor for logging
apiClient.interceptors.request.use(
  (config) => {
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for retry logic
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config;
    if (!config) return Promise.reject(error);

    // Initialize retry count
    config.retryCount = config.retryCount ?? 0;
    const maxRetries = 3;

    // Retry on 5xx or network errors
    if (
      config.retryCount < maxRetries &&
      (error.response?.status >= 500 || error.code === "ECONNABORTED" || !error.response)
    ) {
      config.retryCount += 1;
      const delay = 1000 * Math.pow(2, config.retryCount - 1); // 1s, 2s, 4s
      await new Promise((resolve) => setTimeout(resolve, delay));
      return apiClient(config);
    }

    return Promise.reject(error);
  }
);

// Re-export for backward compatibility
export { API_URL };
