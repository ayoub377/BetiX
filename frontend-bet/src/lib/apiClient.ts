import axios, { AxiosError, AxiosInstance } from 'axios';

import { auth as firebaseAuthInstance } from '@/lib/firebaseConfig';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000/api';

function createApiClient(): AxiosInstance {
  const client = axios.create({ baseURL: API_BASE_URL });

  client.interceptors.request.use(async (config) => {
    const user = firebaseAuthInstance?.currentUser;
    if (user) {
      const token = await user.getIdToken();
      config.headers = config.headers ?? {};
      (config.headers as Record<string, string>).Authorization = `Bearer ${token}`;
    }
    return config;
  });

  return client;
}

export const apiClient = createApiClient();

export function isApiError(err: unknown): err is AxiosError {
  return axios.isAxiosError(err);
}
