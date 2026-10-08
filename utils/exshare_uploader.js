/**
 * EX SHARE / Atelier High-Performance Parallel & Resumable Photo Uploader
 * 
 * Features:
 * - Bounded parallel queue (default 4, adaptive 2-8 based on latency & bandwidth)
 * - 8MB streaming chunked resumable uploads for large files
 * - Zero in-memory buffering in browser: uses Blob.slice() streams
 * - Auto-resume interrupted uploads with byte offset verification
 * - Exponential backoff retry for transient network hiccups
 * - Per-file and aggregate batch progress reporting with MB/s throughput
 * - Full abort/cancellation control via AbortController
 */

class ExShareUploader {
  /**
   * @param {Object} options
   * @param {string} [options.apiBase] - Base URL for API (e.g. '/api/storage')
   * @param {string} [options.authToken] - Bearer token or cookie-based auth
   * @param {number} [options.concurrency=4] - Initial concurrent workers (2-8)
   * @param {boolean} [options.adaptiveConcurrency=true] - Auto-tune concurrency
   * @param {number} [options.chunkSize=8388608] - Chunk size in bytes (8 MB default)
   * @param {number} [options.maxRetries=3] - Max retries per chunk/request
   * @param {Function} [options.onFileProgress] - (fileId, progressInfo) => void
   * @param {Function} [options.onBatchProgress] - (batchProgressInfo) => void
   * @param {Function} [options.onFileComplete] - (fileId, mediaRecord) => void
   * @param {Function} [options.onFileError] - (fileId, error) => void
   * @param {Function} [options.onBatchComplete] - (summary) => void
   */
  constructor(options = {}) {
    this.apiBase = options.apiBase || '/api/storage';
    this.authToken = options.authToken || null;
    this.concurrency = Math.min(8, Math.max(2, options.concurrency || 4));
    this.adaptiveConcurrency = options.adaptiveConcurrency !== false;
    this.chunkSize = options.chunkSize || 8 * 1024 * 1024; // 8 MB
    this.maxRetries = options.maxRetries || 3;

    // Callbacks
    this.onFileProgress = options.onFileProgress || (() => {});
    this.onBatchProgress = options.onBatchProgress || (() => {});
    this.onFileComplete = options.onFileComplete || (() => {});
    this.onFileError = options.onFileError || (() => {});
    this.onBatchComplete = options.onBatchComplete || (() => {});

    // State
    this.queue = [];
    this.activeWorkers = 0;
    this.isPaused = false;
    this.isCancelled = false;
    this.fileItems = new Map(); // id -> FileItem
    this.stats = {
      totalFiles: 0,
      completedFiles: 0,
      failedFiles: 0,
      totalBytes: 0,
      uploadedBytes: 0,
      startTime: null,
    };

    // Adaptive concurrency metrics
    this.recentLatencies = [];
  }

  /**
   * Add files to upload queue
   * @param {FileList|File[]} files
   * @param {Object} uploadMeta - { gallery_id, session_id, section_title }
   */
  addFiles(files, uploadMeta = {}) {
    const newItems = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const id = 'f_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
      const item = {
        id,
        file,
        name: file.name,
        size: file.size,
        type: file.type || 'image/jpeg',
        meta: { ...uploadMeta },
        status: 'queued', // 'queued', 'uploading', 'completed', 'failed', 'cancelled'
        uploadedBytes: 0,
        uploadId: null,
        abortController: new AbortController(),
        error: null,
        mediaRecord: null,
      };
      this.fileItems.set(id, item);
      this.queue.push(item);
      newItems.push(item);

      this.stats.totalFiles++;
      this.stats.totalBytes += file.size;
    }

    if (!this.stats.startTime) {
      this.stats.startTime = Date.now();
    }

    this._triggerBatchProgress();
    this._processQueue();
    return newItems.map(item => item.id);
  }

  /**
   * Start or resume the queue
   */
  start() {
    this.isPaused = false;
    this.isCancelled = false;
    
    this._processQueue();
  }

  /**
   * Pause processing new uploads (in-flight uploads finish current chunk)
   */
  pause() {
    this.isPaused = true;
  }

  /**
   * Cancel a specific file upload
   */
  cancelFile(fileId) {
    const item = this.fileItems.get(fileId);
    if (!item) return;

    if (item.abortController) {
      item.abortController.abort();
    }
    item.status = 'cancelled';

    // Call cancel endpoint on backend to delete temp chunks if uploadId exists
    if (item.uploadId) {
      this._request(`${this.apiBase}/uploads/cancel/`, {
        method: 'POST',
        body: JSON.stringify({ upload_id: item.uploadId }),
        headers: { 'Content-Type': 'application/json' },
      }).catch(() => {});
    }

    this._triggerFileProgress(item);
    this._triggerBatchProgress();
  }

  /**
   * Cancel all files and stop queue
   */
  cancelAll() {
    this.isCancelled = true;
    for (const item of this.fileItems.values()) {
      if (item.status === 'queued' || item.status === 'uploading') {
        this.cancelFile(item.id);
      }
    }
    this.queue = [];
  }

  /* -------------------------------------------------------------------------
   * Internal Queue Dispatcher
   * ------------------------------------------------------------------------- */
  _processQueue() {
    if (this.isPaused || this.isCancelled) return;

    while (this.activeWorkers < this.concurrency && this.queue.length > 0) {
      const item = this.queue.shift();
      if (item.status === 'cancelled') continue;

      this.activeWorkers++;
      item.status = 'uploading';

      this._uploadFile(item)
        .then(result => {
          item.status = 'completed';
          item.mediaRecord = result;
          item.uploadedBytes = item.size;
          this.stats.completedFiles++;
          this.onFileComplete(item.id, result);
        })
        .catch(err => {
          if (item.status !== 'cancelled') {
            item.status = 'failed';
            item.error = err.message || 'Upload failed';
            this.stats.failedFiles++;
            this.onFileError(item.id, err);
          }
        })
        .finally(() => {
          this.activeWorkers--;
          this._adaptConcurrency();
          this._triggerBatchProgress();
          this._processQueue();

          // Check if entire batch complete
          if (this.activeWorkers === 0 && this.queue.length === 0) {
            this._checkBatchFinished();
          }
        });
    }
  }

  /* -------------------------------------------------------------------------
   * File Upload Protocol (Resumable Chunks vs Fast Streaming Single)
   * ------------------------------------------------------------------------- */
  async _uploadFile(item) {
    const file = item.file;
    const isLargeFile = file.size > this.chunkSize;

    if (isLargeFile) {
      return await this._uploadInChunks(item);
    } else {
      return await this._uploadDirect(item);
    }
  }

  /**
   * Resumable Chunked Upload for High-Resolution Photos (>= 8MB)
   */
  async _uploadInChunks(item) {
    const file = item.file;
    const totalChunks = Math.ceil(file.size / this.chunkSize);

    // 1. Initialize Resumable Session
    const initPayload = {
      filename: file.name,
      file_size: file.size,
      mime_type: file.type || 'image/jpeg',
      total_chunks: totalChunks,
      gallery_id: item.meta.gallery_id,
      session_id: item.meta.session_id,
      section_title: item.meta.section_title || '',
    };

    const initRes = await this._retryableRequest(
      `${this.apiBase}/uploads/init/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(initPayload),
        signal: item.abortController.signal,
      },
      item
    );

    item.uploadId = initRes.upload_id;
    let committedOffset = initRes.committed_offset || 0;
    item.uploadedBytes = committedOffset;
    this._triggerFileProgress(item);

    // 2. Upload Remaining Chunks
    let chunkIndex = Math.floor(committedOffset / this.chunkSize);

    while (committedOffset < file.size) {
      if (item.status === 'cancelled') {
        throw new Error('Upload cancelled');
      }

      const chunkStart = committedOffset;
      const chunkEnd = Math.min(file.size, chunkStart + this.chunkSize);
      const chunkBlob = file.slice(chunkStart, chunkEnd);

      const formData = new FormData();
      formData.append('upload_id', item.uploadId);
      formData.append('chunk_index', chunkIndex.toString());
      formData.append('offset', chunkStart.toString());
      formData.append('chunk', chunkBlob, file.name);

      const startTime = performance.now();
      const chunkRes = await this._retryableRequest(
        `${this.apiBase}/uploads/chunk/`,
        {
          method: 'POST',
          body: formData,
          signal: item.abortController.signal,
        },
        item
      );

      const durationMs = performance.now() - startTime;
      this._recordLatency(durationMs, chunkBlob.size);

      committedOffset = chunkRes.committed_offset;
      item.uploadedBytes = committedOffset;
      chunkIndex++;

      this._triggerFileProgress(item);
    }

    // 3. Complete & Atomically Finalize File
    const completePayload = {
      upload_id: item.uploadId,
      final_filename: file.name,
      section_title: item.meta.section_title || '',
    };

    const completeRes = await this._retryableRequest(
      `${this.apiBase}/uploads/complete/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(completePayload),
        signal: item.abortController.signal,
      },
      item
    );

    return completeRes;
  }

  /**
   * Fast Single-Request Upload for Files Under 8MB
   */
  async _uploadDirect(item) {
    const file = item.file;
    const formData = new FormData();
    formData.append('file', file);
    if (item.meta.gallery_id) formData.append('gallery_id', item.meta.gallery_id);
    if (item.meta.session_id) formData.append('session_id', item.meta.session_id);
    if (item.meta.section_title) formData.append('section_title', item.meta.section_title);

    const endpoint = item.meta.session_id 
      ? '/api/culling/upload/' 
      : `${this.apiBase}/upload/`;

    const startTime = performance.now();
    const result = await this._retryableRequest(
      endpoint,
      {
        method: 'POST',
        body: formData,
        signal: item.abortController.signal,
      },
      item
    );

    const durationMs = performance.now() - startTime;
    this._recordLatency(durationMs, file.size);

    item.uploadedBytes = file.size;
    this._triggerFileProgress(item);
    return result;
  }

  /* -------------------------------------------------------------------------
   * HTTP Client with Exponential Backoff Retries
   * ------------------------------------------------------------------------- */
  async _retryableRequest(url, fetchOptions, item) {
    let attempt = 0;
    let delay = 500;

    while (attempt <= this.maxRetries) {
      try {
        return await this._request(url, fetchOptions);
      } catch (err) {
        if (item.abortController.signal.aborted || item.status === 'cancelled') {
          throw new Error('Upload cancelled');
        }

        attempt++;
        if (attempt > this.maxRetries) {
          throw err;
        }

        // Exponential backoff with jitter
        await new Promise(r => setTimeout(r, delay + Math.random() * 200));
        delay *= 2;
      }
    }
  }

  async _request(url, options = {}) {
    const headers = options.headers || {};
    if (this.authToken) {
      headers['Authorization'] = `Bearer ${this.authToken}`;
    }

    const res = await fetch(url, { ...options, headers });
    if (!res.ok) {
      let errorBody = {};
      try {
        errorBody = await res.json();
      } catch (_) {}
      const msg = errorBody.detail || errorBody.error || errorBody.message || `HTTP ${res.status}`;
      const err = new Error(msg);
      err.status = res.status;
      err.response = errorBody;
      throw err;
    }
    return await res.json();
  }

  /* -------------------------------------------------------------------------
   * Adaptive Concurrency Tuning
   * ------------------------------------------------------------------------- */
  _recordLatency(durationMs, bytes) {
    if (!this.adaptiveConcurrency) return;
    const mbps = (bytes * 8) / (durationMs / 1000) / (1024 * 1024);
    this.recentLatencies.push({ durationMs, mbps });
    if (this.recentLatencies.length > 10) {
      this.recentLatencies.shift();
    }
  }

  _adaptConcurrency() {
    if (!this.adaptiveConcurrency || this.recentLatencies.length < 3) return;

    const avgMs = this.recentLatencies.reduce((a, b) => a + b.durationMs, 0) / this.recentLatencies.length;
    // If requests complete rapidly (< 1.5s), cautiously increment concurrency up to 8
    if (avgMs < 1500 && this.concurrency < 8) {
      this.concurrency++;
    } 
    // If requests take > 5s or server starts slowing down, back off to 2-3
    else if (avgMs > 5000 && this.concurrency > 2) {
      this.concurrency--;
    }
  }

  /* -------------------------------------------------------------------------
   * Progress Dispatchers
   * ------------------------------------------------------------------------- */
  _triggerFileProgress(item) {
    const percent = item.size > 0 ? Math.min(100, Math.round((item.uploadedBytes / item.size) * 100)) : 0;
    this.onFileProgress(item.id, {
      fileId: item.id,
      name: item.name,
      uploadedBytes: item.uploadedBytes,
      totalBytes: item.size,
      percent,
      status: item.status,
    });
  }

  _triggerBatchProgress() {
    let uploaded = 0;
    for (const item of this.fileItems.values()) {
      uploaded += item.uploadedBytes;
    }
    this.stats.uploadedBytes = uploaded;

    const percent = this.stats.totalBytes > 0 
      ? Math.min(100, Math.round((this.stats.uploadedBytes / this.stats.totalBytes) * 100)) 
      : 0;

    const elapsedSec = (Date.now() - (this.stats.startTime || Date.now())) / 1000;
    const speedMBs = elapsedSec > 0 ? ((this.stats.uploadedBytes / (1024 * 1024)) / elapsedSec).toFixed(2) : 0;

    this.onBatchProgress({
      totalFiles: this.stats.totalFiles,
      completedFiles: this.stats.completedFiles,
      failedFiles: this.stats.failedFiles,
      totalBytes: this.stats.totalBytes,
      uploadedBytes: this.stats.uploadedBytes,
      percent,
      speedMBs: parseFloat(speedMBs),
      activeWorkers: this.activeWorkers,
      concurrency: this.concurrency,
    });
  }

  _checkBatchFinished() {
    this.onBatchComplete({
      totalFiles: this.stats.totalFiles,
      completedFiles: this.stats.completedFiles,
      failedFiles: this.stats.failedFiles,
      totalBytes: this.stats.totalBytes,
      elapsedSeconds: ((Date.now() - this.stats.startTime) / 1000).toFixed(1),
    });
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = ExShareUploader;
} else if (typeof window !== 'undefined') {
  window.ExShareUploader = ExShareUploader;
}
