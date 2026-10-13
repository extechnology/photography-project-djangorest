import React, { useState, useEffect, useRef, useCallback } from 'react';

/**
 * TypeScript Interfaces for Portfolio Subdomain Provisioning
 */
export type SubdomainStatus = 'pending' | 'provisioning' | 'active' | 'failed' | null;

export interface SubdomainAvailabilityResponse {
  available: boolean;
  subdomain: string;
  is_current_owner?: boolean;
  reason?: string | null;
  code?: string;
  domain?: string;
  live_url?: string;
}

export interface SubdomainClaimResponse {
  status: string;
  message: string;
  subdomain: string;
  subdomain_status: SubdomainStatus;
  domain: string;
  url: string;
  live_url: string;
}

export interface SubdomainStatusResponse {
  subdomain: string | null;
  status: SubdomainStatus;
  error: string | null;
  provisioned_at: string | null;
  dns_checked_at: string | null;
  dns_record_type: string;
  dns_provider: string;
  retry_count: number;
  last_retry_at: string | null;
  domain: string | null;
  live_url: string | null;
}

interface PortfolioSubdomainFormProps {
  /**
   * Base API URL (e.g. 'https://server.exshare.ai' or '' if proxying /api/)
   */
  apiBaseUrl?: string;
  /**
   * Current authentication bearer token
   */
  authToken?: string;
  /**
   * Root portfolio domain (default: 'exshare.ai')
   */
  portfolioDomain?: string;
  /**
   * Callback on status change or successful activation
   */
  onSubdomainActive?: (liveUrl: string) => void;
}

/**
 * Validation Regex & Rules
 * - 3 to 63 lowercase alphanumeric characters and hyphens
 * - Cannot start or end with a hyphen
 * - No dots, spaces, underscores, URLs
 */
const SUBDOMAIN_REGEX = /^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$/;
const RESERVED_NAMES = new Set([
  'www', 'app', 'api', 'admin', 'auth', 'mail', 'smtp', 'ftp', 'static', 'media',
  'cdn', 'support', 'staging', 'dev', 'status', 'dashboard', 'billing', 'gallery',
  'exshare', 'server', 'srv', 'ns1', 'ns2'
]);

export const PortfolioSubdomainForm: React.FC<PortfolioSubdomainFormProps> = ({
  apiBaseUrl = '',
  authToken,
  portfolioDomain = 'exshare.ai',
  onSubdomainActive,
}) => {
  // Local Form States
  const [subdomainInput, setSubdomainInput] = useState<string>('');
  const [currentSubdomain, setCurrentSubdomain] = useState<string | null>(null);
  const [provisioningStatus, setProvisioningStatus] = useState<SubdomainStatus>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [statusDetails, setStatusDetails] = useState<SubdomainStatusResponse | null>(null);

  // Availability Check States
  const [isCheckingAvailability, setIsCheckingAvailability] = useState<boolean>(false);
  const [availabilityResult, setAvailabilityResult] = useState<SubdomainAvailabilityResponse | null>(null);
  const [clientValidationError, setClientValidationError] = useState<string | null>(null);

  // Action Loading & Throttling
  const [isSubmittingClaim, setIsSubmittingClaim] = useState<boolean>(false);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);
  const [retryCooldown, setRetryCooldown] = useState<number>(0);
  const [isCopied, setIsCopied] = useState<boolean>(false);

  // Debounce & Polling References
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  const pollingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const activeReqIdRef = useRef<number>(0);

  // Common Headers
  const getHeaders = useCallback(() => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
    if (authToken) {
      headers['Authorization'] = authToken.startsWith('Bearer ') || authToken.startsWith('Token ')
        ? authToken
        : `Bearer ${authToken}`;
    }
    return headers;
  }, [authToken]);

  /**
   * 1. Fetch current status on mount
   */
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl}/api/portfolio/subdomain/status/`, {
        method: 'GET',
        headers: getHeaders(),
      });
      if (res.ok) {
        const data: SubdomainStatusResponse = await res.json();
        setStatusDetails(data);
        setCurrentSubdomain(data.subdomain);
        setProvisioningStatus(data.status);
        if (data.subdomain && !subdomainInput) {
          setSubdomainInput(data.subdomain);
        }
        if (data.status === 'active' && data.live_url && onSubdomainActive) {
          onSubdomainActive(data.live_url);
        }
      }
    } catch (err) {
      console.error('Failed to load portfolio subdomain status:', err);
    }
  }, [apiBaseUrl, getHeaders, onSubdomainActive, subdomainInput]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  /**
   * 2. Poll status every 4s when status is pending or provisioning
   */
  useEffect(() => {
    if (provisioningStatus === 'pending' || provisioningStatus === 'provisioning') {
      pollingTimerRef.current = setInterval(() => {
        fetchStatus();
      }, 4000);
    } else {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    }
    return () => {
      if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    };
  }, [provisioningStatus, fetchStatus]);

  /**
   * 3. Handle Retry Cooldown Timer
   */
  useEffect(() => {
    if (retryCooldown <= 0) return;
    const timer = setInterval(() => {
      setRetryCooldown(prev => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [retryCooldown]);

  /**
   * 4. Client-side Format Validation
   */
  const validateFormat = (name: string): string | null => {
    const clean = name.trim().toLowerCase();
    if (!clean) return 'Please enter a subdomain.';
    if (clean.length < 3) return 'Subdomain must be at least 3 characters.';
    if (clean.length > 63) return 'Subdomain cannot exceed 63 characters.';
    if (clean.startsWith('-') || clean.endsWith('-')) return 'Subdomain cannot start or end with a hyphen.';
    if (/[._\s/:\\]/.test(clean)) return 'Dots, spaces, underscores, and URLs are not allowed.';
    if (!SUBDOMAIN_REGEX.test(clean)) return 'Only lowercase letters, numbers, and hyphens are allowed.';
    if (RESERVED_NAMES.has(clean)) return `"${clean}" is reserved for platform infrastructure.`;
    return null;
  };

  /**
   * 5. Debounced Server Availability Check
   */
  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawVal = e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '');
    setSubdomainInput(rawVal);
    setErrorMessage(null);

    const validationErr = validateFormat(rawVal);
    setClientValidationError(validationErr);

    if (validationErr) {
      setAvailabilityResult(null);
      setIsCheckingAvailability(false);
      return;
    }

    if (currentSubdomain && rawVal === currentSubdomain) {
      setAvailabilityResult({
        available: true,
        subdomain: rawVal,
        is_current_owner: true,
        domain: `${rawVal}.${portfolioDomain}`,
        live_url: `https://${rawVal}.${portfolioDomain}`,
      });
      setIsCheckingAvailability(false);
      return;
    }

    // Debounce 400ms
    setIsCheckingAvailability(true);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

    const reqId = ++activeReqIdRef.current;
    debounceTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetch(
          `${apiBaseUrl}/api/portfolio/subdomain/availability/?name=${encodeURIComponent(rawVal)}`,
          { method: 'GET', headers: getHeaders() }
        );
        const data: SubdomainAvailabilityResponse = await res.json();
        // Prevent race condition from stale debounced requests
        if (reqId === activeReqIdRef.current) {
          setAvailabilityResult(data);
          setIsCheckingAvailability(false);
        }
      } catch {
        if (reqId === activeReqIdRef.current) {
          setIsCheckingAvailability(false);
        }
      }
    }, 400);
  };

  /**
   * 6. Claim Subdomain Submission
   */
  const handleSubmitClaim = async (e: React.FormEvent) => {
    e.preventDefault();
    const clean = subdomainInput.trim().toLowerCase();
    const valErr = validateFormat(clean);
    if (valErr) {
      setClientValidationError(valErr);
      return;
    }

    setIsSubmittingClaim(true);
    setErrorMessage(null);

    try {
      const res = await fetch(`${apiBaseUrl}/api/portfolio/subdomain/`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify({ subdomain: clean }),
      });
      const data = await res.json();

      if (res.status === 202 || res.status === 200) {
        setCurrentSubdomain(data.subdomain);
        setProvisioningStatus(data.subdomain_status || 'pending');
        fetchStatus();
      } else if (res.status === 409) {
        setErrorMessage(data.error || 'This subdomain was just claimed by another user.');
        setAvailabilityResult({ available: false, subdomain: clean, reason: 'already_taken' });
      } else {
        setErrorMessage(data.error || 'Failed to claim subdomain.');
      }
    } catch {
      setErrorMessage('Network connection error. Please try again.');
    } finally {
      setIsSubmittingClaim(false);
    }
  };

  /**
   * 7. Retry Failed DNS Provisioning
   */
  const handleRetryProvisioning = async () => {
    if (retryCooldown > 0) return;
    setIsRetrying(true);
    setErrorMessage(null);

    try {
      const res = await fetch(`${apiBaseUrl}/api/portfolio/subdomain/retry/`, {
        method: 'POST',
        headers: getHeaders(),
      });
      const data = await res.json();

      if (res.status === 202 || res.status === 200) {
        setProvisioningStatus('pending');
        setRetryCooldown(30); // 30-second cooldown
        fetchStatus();
      } else if (res.status === 429) {
        setRetryCooldown(data.cooldown_remaining || 30);
        setErrorMessage(`Please wait ${data.cooldown_remaining || 30} seconds before retrying.`);
      } else {
        setErrorMessage(data.error || 'Could not retry DNS provisioning.');
      }
    } catch {
      setErrorMessage('Network connection error while retrying.');
    } finally {
      setIsRetrying(false);
    }
  };

  /**
   * 8. Copy Live URL to Clipboard
   */
  const copyToClipboard = (url: string) => {
    navigator.clipboard.writeText(url);
    setIsCopied(true);
    setTimeout(() => setIsCopied(false), 2000);
  };

  const previewUrl = subdomainInput.trim()
    ? `https://${subdomainInput.trim()}.${portfolioDomain}`
    : `https://your-name.${portfolioDomain}`;

  const isFormDisabled =
    isSubmittingClaim ||
    provisioningStatus === 'pending' ||
    provisioningStatus === 'provisioning';

  return (
    <div className="w-full max-w-2xl bg-neutral-900 border border-neutral-800 rounded-2xl p-6 sm:p-8 text-neutral-100 shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between pb-6 border-b border-neutral-800">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
            <span>Custom Portfolio Subdomain</span>
            {provisioningStatus === 'active' && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                Live & Active
              </span>
            )}
          </h2>
          <p className="text-sm text-neutral-400 mt-1">
            Publish your photography portfolio with an exclusive branded address.
          </p>
        </div>
      </div>

      {/* Main Form */}
      <form onSubmit={handleSubmitClaim} className="mt-6 space-y-6">
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wider text-neutral-400 mb-2">
            Subdomain Handle
          </label>
          <div className="relative flex rounded-xl shadow-inner bg-neutral-950 border border-neutral-800 focus-within:border-amber-500 transition-colors">
            <input
              type="text"
              id="subdomain-input"
              value={subdomainInput}
              onChange={handleInputChange}
              disabled={isFormDisabled}
              placeholder="e.g. mridhul"
              className="flex-1 bg-transparent px-4 py-3 text-neutral-100 placeholder-neutral-600 outline-none text-base font-mono disabled:opacity-50"
              maxLength={63}
            />
            <span className="inline-flex items-center px-4 py-3 text-sm text-neutral-400 bg-neutral-900/60 border-l border-neutral-800 font-mono select-none">
              .{portfolioDomain}
            </span>
          </div>

          {/* Availability / Validation Status Pill */}
          <div className="mt-2.5 min-h-[24px] text-xs flex items-center gap-2">
            {isCheckingAvailability && (
              <span className="text-neutral-400 flex items-center gap-1.5 animate-pulse">
                <svg className="w-3.5 h-3.5 animate-spin text-amber-400" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Checking availability...
              </span>
            )}

            {!isCheckingAvailability && clientValidationError && (
              <span className="text-rose-400 flex items-center gap-1">
                ⚠️ {clientValidationError}
              </span>
            )}

            {!isCheckingAvailability && !clientValidationError && availabilityResult && (
              availabilityResult.available ? (
                <span className="text-emerald-400 flex items-center gap-1 font-medium">
                  ✓ {availabilityResult.is_current_owner
                    ? 'Current active subdomain'
                    : `"${availabilityResult.subdomain}" is available!`}
                </span>
              ) : (
                <span className="text-rose-400 flex items-center gap-1 font-medium">
                  ✗ Subdomain unavailable ({availabilityResult.reason || 'Already in use'})
                </span>
              )
            )}
          </div>
        </div>

        {/* Live URL Preview Card */}
        <div className="p-4 rounded-xl bg-neutral-950/60 border border-neutral-800/80 flex items-center justify-between">
          <div className="flex items-center gap-3 overflow-hidden">
            <div className="w-8 h-8 rounded-lg bg-neutral-800 flex items-center justify-center text-neutral-400 shrink-0">
              🌐
            </div>
            <div className="overflow-hidden">
              <div className="text-xs text-neutral-500 font-medium">URL Preview</div>
              <div className="text-sm font-mono text-neutral-200 truncate">{previewUrl}</div>
            </div>
          </div>
          {provisioningStatus === 'active' && statusDetails?.live_url && (
            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copyToClipboard(statusDetails.live_url!)}
                className="px-3 py-1.5 rounded-lg bg-neutral-800 hover:bg-neutral-700 text-xs text-neutral-300 transition-colors"
              >
                {isCopied ? 'Copied! ✓' : 'Copy Link'}
              </button>
              <a
                href={statusDetails.live_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-3 py-1.5 rounded-lg bg-amber-500/10 hover:bg-amber-500/20 text-xs font-semibold text-amber-400 border border-amber-500/30 transition-colors"
              >
                Visit Site ↗
              </a>
            </div>
          )}
        </div>

        {/* Provisioning State Notification Banners */}
        {provisioningStatus === 'pending' || provisioningStatus === 'provisioning' ? (
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex items-start gap-3 text-amber-200">
            <svg className="w-5 h-5 text-amber-400 animate-spin shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            <div className="text-xs leading-relaxed">
              <p className="font-semibold text-amber-300">DNS Provisioning in Progress...</p>
              <p className="text-amber-200/80 mt-0.5">
                Configuring DNS records on GoDaddy and preparing SSL certificate. This typically completes in 1–2 minutes.
              </p>
            </div>
          </div>
        ) : null}

        {provisioningStatus === 'failed' && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-start justify-between gap-3 text-rose-200">
            <div className="text-xs">
              <p className="font-semibold text-rose-300">DNS Provisioning Failed</p>
              <p className="text-rose-200/80 mt-0.5">
                {statusDetails?.error || errorMessage || 'An unexpected DNS conflict or server error occurred.'}
              </p>
            </div>
            <button
              type="button"
              onClick={handleRetryProvisioning}
              disabled={isRetrying || retryCooldown > 0}
              className="shrink-0 px-3 py-1.5 rounded-lg bg-rose-500 text-white text-xs font-medium hover:bg-rose-600 disabled:opacity-50 transition-colors"
            >
              {retryCooldown > 0 ? `Wait ${retryCooldown}s` : isRetrying ? 'Retrying...' : 'Retry Now'}
            </button>
          </div>
        )}

        {errorMessage && provisioningStatus !== 'failed' && (
          <div className="p-3 rounded-lg bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
            {errorMessage}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-neutral-800">
          <button
            type="submit"
            disabled={
              isSubmittingClaim ||
              !subdomainInput.trim() ||
              Boolean(clientValidationError) ||
              availabilityResult?.available === false ||
              (currentSubdomain === subdomainInput.trim() && provisioningStatus === 'active') ||
              provisioningStatus === 'pending' ||
              provisioningStatus === 'provisioning'
            }
            className="px-6 py-2.5 rounded-xl font-medium text-sm transition-all duration-200 bg-amber-500 hover:bg-amber-400 text-neutral-950 disabled:bg-neutral-800 disabled:text-neutral-500 disabled:cursor-not-allowed shadow-lg shadow-amber-500/10 flex items-center gap-2"
          >
            {isSubmittingClaim ? (
              <>
                <svg className="w-4 h-4 animate-spin text-neutral-950" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                <span>Reserving...</span>
              </>
            ) : (
              <span>Save & Connect Subdomain</span>
            )}
          </button>
        </div>
      </form>
    </div>
  );
};

export default PortfolioSubdomainForm;
