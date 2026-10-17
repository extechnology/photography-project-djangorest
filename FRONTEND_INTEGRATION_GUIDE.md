# Frontend Integration Guide: Rate Limiting (Throttling) & API Resiliency

This document provides a guide and drop-in code snippets for frontend applications (React / Next.js / TypeScript) interacting with the backend APIs following the implementation of rate limiting and throttling.

---

## 1. Overview of Backend Rate Limits

The backend enforces rate limiting via Django REST Framework (DRF) backed by memory cache. When a user or IP exceeds the permitted rate, the backend responds with:
- **HTTP Status Code**: `429 Too Many Requests`
- **Response Header**: `Retry-After: <seconds>` (e.g. `Retry-After: 48`)
- **JSON Payload**:
  ```json
  {
    "detail": "Request was throttled. Expected available in 48 seconds."
  }
  ```

### Active Rate Limits

| Scope | Rate Limit | Affected Endpoints | Recommended Frontend UX |
| :--- | :--- | :--- | :--- |
| `login` | **10 / min** | `POST /api/auth/login/` | Disable submit on click; show retry countdown if 429. |
| `register` | **5 / min** | `POST /api/auth/register/` | Disable submit on click; prevent multiple clicks. |
| `otp_send` | **5 / min** | `POST /api/auth/resend-otp/`<br>`POST /api/auth/passwordless/send-otp/`<br>`POST /api/auth/reset-password/otp/` | **Enforce a 60-second cooldown timer** on the "Resend Code" button. |
| `otp_verify` | **10 / min** | `POST /api/auth/verify-otp/`<br>`POST /api/auth/passwordless/verify-otp/` | Disable submit on verification; lock input during validation. |
| `availability_check` | **45 / min** | `GET /api/auth/check-username/`<br>`GET /api/auth/check-identifier/`<br>`GET /api/portfolio/subdomain/availability/` | **Debounce input checks by 350ms–500ms** so individual keystrokes do not spam the API. |
| `password_verify` | **10 / min** | `POST /api/shared-galleries/{token}/verify-password/`<br>`POST /api/public/galleries/{id}/verify-pin/` | Show remaining attempts or lock out password box for duration on 429. |
| `inquiry_submit` | **10 / min** | `POST /api/public/inquiries/`<br>`POST /api/public/portfolio-site/inquiries/` | Show loading spinner on submission; clear form only on success. |
| `view_track` | **60 / min** | `POST /api/public/portfolio/{slug}/track-view/`<br>`POST /api/public/portfolio-site/track-view/` | Deduplicate telemetry per session with `sessionStorage`. |
| `subdomain_claim` | **10 / min** | `POST /api/portfolio/subdomain/`<br>`POST /api/portfolio/subdomain/retry/` | Enforce 30s client-side cooldown on retry button. |
| `checkout` | **15 / min** | `POST /api/plans/checkout/`<br>`POST /api/plans/verify/` | Disable button immediately after click to prevent double order generation. |
| `face_search` | **15 / min** | `POST /api/events/{id}/face-search/` | Show animated scanning state; prevent multi-submits. |
| `bulk_download` | **10 / min** | `GET /api/public/galleries/{id}/download-zip/` | Show "Preparing ZIP..." loader; disable repeat clicks. |

---

## 2. Global Axios Interceptor (HTTP 429 Handling)

Add this interceptor to your central Axios client (`api.ts` or `client.ts`). It automatically captures `429` responses, extracts the `Retry-After` header or parseable duration from the response body, and displays a toast message or dispatches an event.

```typescript
// src/api/axiosClient.ts
import axios, { AxiosError, AxiosResponse } from 'axios';
import { toast } from 'react-hot-toast'; // Or your UI library: sonner, antd, material-ui, etc.

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'https://server.exshare.ai',
  withCredentials: true, // For HTTP-only JWT cookies
});

// Response Interceptor
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError<{ detail?: string }>) => {
    if (error.response?.status === 429) {
      // 1. Extract retry seconds from response header or body text
      const retryAfterHeader = error.response.headers['retry-after'];
      let seconds = retryAfterHeader ? parseInt(retryAfterHeader, 10) : null;

      if (!seconds && error.response.data?.detail) {
        const match = error.response.data.detail.match(/(\d+)\s*seconds?/i);
        if (match) {
          seconds = parseInt(match[1], 10);
        }
      }

      // 2. User-friendly message
      const waitMessage = seconds
        ? `Too many attempts. Please wait ${seconds}s before trying again.`
        : 'Too many requests. Please wait a moment before trying again.';

      toast.error(waitMessage, {
        id: 'throttle-rate-limit-toast', // Prevent stacked duplicate toasts
        duration: (seconds ? seconds * 1000 : 4000),
      });

      // Optional: Emit custom window event for components with countdown timers
      window.dispatchEvent(
        new CustomEvent('api-throttled', {
          detail: { seconds: seconds || 30, url: error.config?.url },
        })
      );
    }

    return Promise.reject(error);
  }
);

export default apiClient;
```

---

## 3. UI Component Updates

### A. OTP Resend Button (60s Cooldown Timer)

Prevents users from hitting the `5/min` OTP send rate limit by showing a countdown timer.

```tsx
// src/components/auth/OtpResendButton.tsx
import React, { useState, useEffect } from 'react';
import apiClient from '@/api/axiosClient';
import { toast } from 'react-hot-toast';

interface OtpResendButtonProps {
  emailOrPhone: string;
  endpoint?: string;
  cooldownSeconds?: number;
}

export const OtpResendButton: React.FC<OtpResendButtonProps> = ({
  emailOrPhone,
  endpoint = '/api/auth/resend-otp/',
  cooldownSeconds = 60,
}) => {
  const [countdown, setCountdown] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (countdown <= 0) return;
    const interval = setInterval(() => {
      setCountdown((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(interval);
  }, [countdown]);

  const handleResend = async () => {
    if (countdown > 0 || loading) return;
    setLoading(true);

    try {
      await apiClient.post(endpoint, { email: emailOrPhone, identifier: emailOrPhone });
      toast.success('Verification code resent successfully.');
      setCountdown(cooldownSeconds);
    } catch (err: any) {
      if (err.response?.status === 429) {
        // If throttled by server, sync countdown to server time
        const match = err.response.data?.detail?.match(/(\d+)\s*seconds?/i);
        const retrySec = match ? parseInt(match[1], 10) : 60;
        setCountdown(retrySec);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleResend}
      disabled={countdown > 0 || loading}
      className="text-sm font-medium text-emerald-600 hover:text-emerald-500 disabled:text-gray-400 disabled:cursor-not-allowed transition-colors"
    >
      {loading ? (
        'Sending...'
      ) : countdown > 0 ? (
        `Resend code in ${countdown}s`
      ) : (
        'Resend verification code'
      )}
    </button>
  );
};
```

---

### B. Debounced Availability Check (Username & Subdomain)

Avoid making a network request on every keystroke by using a debounce hook:

```tsx
// src/hooks/useDebounce.ts
import { useState, useEffect } from 'react';

export function useDebounce<T>(value: T, delay: number = 400): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value);
    }, delay);

    return () => clearTimeout(handler);
  }, [value, delay]);

  return debouncedValue;
}
```

**Usage in Username / Subdomain Input**:
```tsx
import React, { useState, useEffect } from 'react';
import { useDebounce } from '@/hooks/useDebounce';
import apiClient from '@/api/axiosClient';

export const UsernameCheckInput = () => {
  const [username, setUsername] = useState('');
  const [isAvailable, setIsAvailable] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState('');

  const debouncedUsername = useDebounce(username, 400);

  useEffect(() => {
    if (!debouncedUsername || debouncedUsername.trim().length < 3) {
      setIsAvailable(null);
      setMessage('');
      return;
    }

    let isMounted = true;
    setChecking(true);

    apiClient
      .get(`/api/auth/check-username/`, { params: { username: debouncedUsername } })
      .then((res) => {
        if (isMounted) {
          setIsAvailable(res.data.is_available);
          setMessage(res.data.message);
        }
      })
      .catch((err) => {
        if (isMounted) {
          if (err.response?.status === 429) {
            setMessage('Checking too fast. Please pause for a moment.');
          }
          setIsAvailable(false);
        }
      })
      .finally(() => {
        if (isMounted) setChecking(false);
      });

    return () => {
      isMounted = false;
    };
  }, [debouncedUsername]);

  return (
    <div>
      <input
        type="text"
        value={username}
        onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/[^a-z0-9_.]/g, ''))}
        placeholder="Choose username"
        className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none"
      />
      {checking && <p className="text-xs text-gray-500 mt-1">Checking availability...</p>}
      {!checking && isAvailable === true && (
        <p className="text-xs text-green-600 mt-1 font-medium">{message || 'Username available'}</p>
      )}
      {!checking && isAvailable === false && (
        <p className="text-xs text-red-600 mt-1 font-medium">{message || 'Username is unavailable'}</p>
      )}
    </div>
  );
};
```

---

### C. Public Inquiry Form (Double-Submit & Throttling Protection)

```tsx
// src/components/portfolio/InquiryForm.tsx
import React, { useState } from 'react';
import apiClient from '@/api/axiosClient';
import { toast } from 'react-hot-toast';

export const PublicInquiryForm = ({ photographerId }: { photographerId?: string }) => {
  const [formData, setFormData] = useState({
    client_name: '',
    client_email: '',
    client_phone: '',
    event_type: 'wedding',
    message: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitting || cooldown > 0) return;

    setSubmitting(true);
    try {
      await apiClient.post('/api/public/inquiries/', {
        ...formData,
        photographer_id: photographerId,
      });
      toast.success('Inquiry sent successfully! The studio will contact you soon.');
      setFormData({ client_name: '', client_email: '', client_phone: '', event_type: 'wedding', message: '' });
      setCooldown(15); // Local 15-second grace period
    } catch (err: any) {
      if (err.response?.status === 429) {
        toast.error('You have sent several messages. Please wait a minute before sending another.');
      } else {
        toast.error(err.response?.data?.message || 'Failed to submit inquiry.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <input
        required
        type="text"
        placeholder="Your Full Name"
        value={formData.client_name}
        onChange={(e) => setFormData({ ...formData, client_name: e.target.value })}
        className="w-full px-4 py-2 border rounded-md"
      />
      <input
        required
        type="email"
        placeholder="Your Email"
        value={formData.client_email}
        onChange={(e) => setFormData({ ...formData, client_email: e.target.value })}
        className="w-full px-4 py-2 border rounded-md"
      />
      <textarea
        required
        rows={4}
        placeholder="Tell us about your event..."
        value={formData.message}
        onChange={(e) => setFormData({ ...formData, message: e.target.value })}
        className="w-full px-4 py-2 border rounded-md"
      />
      <button
        type="submit"
        disabled={submitting || cooldown > 0}
        className="w-full bg-emerald-600 text-white font-medium py-2 rounded-md hover:bg-emerald-700 disabled:opacity-50 transition"
      >
        {submitting ? 'Sending...' : cooldown > 0 ? `Please wait ${cooldown}s` : 'Send Booking Inquiry'}
      </button>
    </form>
  );
};
```

---

### D. Visitor Analytics Deduplication

Prevent rapid page refreshes from consuming the `60/min` view tracking quota:

```typescript
// src/utils/trackPortfolioView.ts
import apiClient from '@/api/axiosClient';

export function trackPortfolioView(slug: string, section: string = 'hero') {
  if (typeof window === 'undefined') return;

  const sessionKey = `tracked_view_${slug}_${section}`;
  // Only track once per browser tab session
  if (sessionStorage.getItem(sessionKey)) {
    return;
  }

  sessionStorage.setItem(sessionKey, '1');

  apiClient
    .post(`/api/public/portfolio/${slug}/track-view/`, {
      page_section: section,
      device: window.innerWidth < 768 ? 'mobile' : 'desktop',
    })
    .catch(() => {
      // Suppress analytics telemetry errors silently
    });
}
```

---

## 4. Frontend Checklist Summary

- [x] **Global Axios Interceptor**: Configured to capture `status === 429` and surface `Retry-After` seconds.
- [x] **OTP Resend Countdown**: Added a 60-second client-side cooldown on the "Resend Code" trigger.
- [x] **Input Debouncing**: Added 400ms debounce on `check-username` and `subdomain/availability`.
- [x] **Double-Click Prevention**: Disabled buttons immediately on submit for Login, Register, Checkout, and Inquiry forms.
- [x] **Analytics Telemetry**: Deduplicated view tracking per browser session via `sessionStorage`.
