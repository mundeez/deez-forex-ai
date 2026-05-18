/**
 * Toast notification helpers using sonner.
 * Integrates with the Redux store for consistent UI feedback.
 */

import { toast } from "sonner";

export const showSuccess = (message: string) => {
  toast.success(message);
};

export const showError = (message: string) => {
  toast.error(message);
};

export const showInfo = (message: string) => {
  toast.info(message);
};

export const showWarning = (message: string) => {
  toast.warning(message);
};

export const showLoading = (message: string, promise: Promise<any>) => {
  toast.promise(promise, {
    loading: message,
    success: (data: any) => data?.message || "Completed successfully",
    error: (err: any) => err?.message || "Something went wrong",
  });
};
