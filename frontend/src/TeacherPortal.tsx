import React, { useState } from 'react';
import { API_BASE, authHeadersMultipart } from './config';

interface TeacherPortalProps {
  userId: string;
  activeTab: 'upload' | 'materials';
}

interface UploadRecord {
  filename: string;
  classId: string;
  subject: string;
  chunks: number;
  date: string;
}

export const TeacherPortal: React.FC<TeacherPortalProps> = ({ userId, activeTab }) => {
  const [classId, setClassId] = useState('');
  const [subject, setSubject] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [uploads, setUploads] = useState<UploadRecord[]>([]);

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !classId.trim() || !subject.trim()) {
      setToast({ message: 'Please fill all fields and select a file.', type: 'error' });
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);
    formData.append('class_id', classId);
    formData.append('subject', subject);

    try {
      const headers = await authHeadersMultipart(userId);
      const res = await fetch(`${API_BASE}/teacher/upload`, {
        method: 'POST', headers, body: formData
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const record: UploadRecord = {
        filename: file.name,
        classId, subject,
        chunks: data.chunks || 0,
        date: new Date().toLocaleDateString()
      };
      setUploads(prev => [record, ...prev]);
      setToast({ message: `Uploaded successfully — ${data.chunks} study sections created for ${classId} / ${subject}`, type: 'success' });
      setFile(null);
      setClassId('');
      setSubject('');
    } catch (err: any) {
      setToast({ message: err.message || 'Upload failed.', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="teacher-content">
      {activeTab === 'upload' ? (
        <form className="upload-form" onSubmit={handleUpload}>
          <h2>Upload Study Materials</h2>
          <p>Upload textbooks or notes for your students. Files are processed into study sections automatically.</p>

          <div className="field">
            <label>Class</label>
            <input type="text" value={classId} onChange={e => setClassId(e.target.value)} placeholder="e.g. SSS 1" />
          </div>
          <div className="field">
            <label>Subject</label>
            <input type="text" value={subject} onChange={e => setSubject(e.target.value)} placeholder="e.g. Biology" />
          </div>

          <div className="dropzone">
            {file ? (
              <span className="selected-file">📄 {file.name}</span>
            ) : (
              <span>Click or drag a file here (PDF, TXT, MD)</span>
            )}
            <input type="file" onChange={e => setFile(e.target.files?.[0] || null)} accept=".pdf,.txt,.md" />
          </div>

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Processing...' : 'Upload'}
          </button>
        </form>
      ) : (
        <div className="materials-table">
          <h2>Uploaded Materials</h2>
          {uploads.length === 0 ? (
            <div className="materials-empty">
              No materials uploaded yet. Upload your first file to get started.
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Class</th>
                  <th>Subject</th>
                  <th>Sections</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {uploads.map((u, i) => (
                  <tr key={i}>
                    <td>{u.filename}</td>
                    <td>{u.classId}</td>
                    <td>{u.subject}</td>
                    <td>{u.chunks}</td>
                    <td>{u.date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
          <button className="toast-close" onClick={() => setToast(null)}>×</button>
        </div>
      )}
    </div>
  );
};
