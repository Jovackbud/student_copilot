import React, { useState, useEffect, useRef } from 'react';
import { TeacherPortal } from './TeacherPortal';
import { RevisionMode } from './RevisionMode';
import { AuthScreen } from './AuthScreen';
import { API_BASE, authHeaders, authHeadersMultipart, checkAuthExpiry } from './config';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import './index.css';

interface Profile {
  name: string;
  age: string;
  country: string;
  grade: string;
  learning_method?: string;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

function App() {
  // Auth
  const [currentUser, setCurrentUser] = useState<string | null>(localStorage.getItem('current_user'));
  const [currentRole, setCurrentRole] = useState<string | null>(localStorage.getItem('current_role'));

  // Navigation
  const [tab, setTab] = useState<'chat' | 'revision'>('chat');
  const [teacherTab, setTeacherTab] = useState<'upload' | 'materials'>('upload');

  // Profile (hidden from default view)
  const [profile, setProfile] = useState<Profile>({ name: '', age: '', country: '', grade: '' });
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Chat state
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [activeSubject, setActiveSubject] = useState('');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const prevConvRef = useRef<string | null>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-dismiss toast
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 5000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  // Load profile on login
  useEffect(() => {
    if (!currentUser) return;
    (async () => {
      try {
        const headers = await authHeaders(currentUser);
        const res = await fetch(`${API_BASE}/users/me`, { headers });
        checkAuthExpiry(res);
        if (res.ok) {
          const data = await res.json();
          setProfile({
            name: data.full_name || '',
            age: data.age || '',
            country: data.country || '',
            grade: data.class_id || '',
            learning_method: data.learning_method || ''
          });
        }
      } catch (err) {
        console.error('Failed to load profile', err);
      }
    })();
  }, [currentUser]);

  // Init conversation for chat mode
  useEffect(() => {
    if (!currentUser || currentRole === 'teacher') return;
    if (tab !== 'chat' || activeSubject) return; // Only for general chat (no subject = general mode)
    if (convId) return;
    (async () => {
      try {
        const headers = await authHeaders(currentUser);
        const res = await fetch(`${API_BASE}/conversations/new`, {
          method: 'POST', headers, body: JSON.stringify({})
        });
        checkAuthExpiry(res);
        const data = await res.json();
        setConvId(data.conversation_id);
      } catch (err) {
        console.error('Failed to create conversation', err);
      }
    })();
  }, [tab, currentUser, activeSubject]);

  // Silent learning sync — end previous conversation in background
  const syncLearningProfile = async (convIdToEnd: string) => {
    if (!currentUser || convIdToEnd.startsWith('notebook_temp_')) return;
    try {
      const headers = await authHeaders(currentUser);
      const res = await fetch(`${API_BASE}/conversations/${convIdToEnd}/end`, {
        method: 'POST', headers
      });
      if (res.ok) {
        const data = await res.json();
        if (data.learning_method) {
          setProfile(prev => ({ ...prev, learning_method: data.learning_method }));
        }
      }
    } catch {} // Silent — never block the user
  };

  // Sync on tab close / navigate away
  useEffect(() => {
    const handleUnload = () => {
      if (convId && currentUser && !convId.startsWith('notebook_temp_')) {
        const token = localStorage.getItem(`jwt_${currentUser}`);
        if (token) {
          navigator.sendBeacon(
            `${API_BASE}/conversations/${convId}/end`,
            new Blob([JSON.stringify({})], { type: 'application/json' })
          );
        }
      }
    };
    window.addEventListener('beforeunload', handleUnload);
    return () => window.removeEventListener('beforeunload', handleUnload);
  }, [convId, currentUser]);

  const handleNewChat = async () => {
    // Sync previous conversation silently
    if (convId) {
      prevConvRef.current = convId;
      syncLearningProfile(convId);
    }
    setMessages([]);
    setConvId(null);
    setActiveSubject('');
    // New conversation will be created by useEffect
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim() || loading) return;

    const isNotebook = !!activeSubject.trim();

    if (!isNotebook && !convId) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setLoading(true);

    try {
      const endpoint = isNotebook ? `${API_BASE}/notebook/ask` : `${API_BASE}/chat`;
      const body = isNotebook
        ? { question: userMsg, active_subject: activeSubject, active_class: profile.grade }
        : {
            conversation_id: convId,
            message: userMsg,
            user_profile: {
              full_name: profile.name, age: profile.age,
              country: profile.country, class_id: profile.grade
            }
          };

      const headers = await authHeaders(currentUser!);
      const res = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(body) });
      checkAuthExpiry(res);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply || data.answer }]);
    } catch (err: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Something went wrong: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0]) return;
    const selectedFile = e.target.files[0];
    const isNotebook = !!activeSubject.trim();

    if (!isNotebook && !convId) return;
    setUploading(true);

    const formData = new FormData();
    formData.append('file', selectedFile);
    if (isNotebook) {
      formData.append('subject', activeSubject || 'General');
      formData.append('class_id', profile.grade || 'General');
    }

    try {
      const endpoint = isNotebook
        ? `${API_BASE}/notebook/upload`
        : `${API_BASE}/upload?conversation_id=${convId}`;
      const headers = await authHeadersMultipart(currentUser!);
      const res = await fetch(endpoint, { method: 'POST', headers, body: formData });
      checkAuthExpiry(res);
      const data = await res.json();
      if (isNotebook && data.chunks) {
        setToast({ message: `${selectedFile.name} processed — ${data.chunks} study sections created.`, type: 'success' });
      } else if (data.summary) {
        setToast({ message: `File uploaded successfully.`, type: 'success' });
      }
    } catch (err) {
      setToast({ message: 'Upload failed. Please try again.', type: 'error' });
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleLogout = () => {
    // Sync before logout
    if (convId) syncLearningProfile(convId);
    localStorage.removeItem('current_user');
    localStorage.removeItem('current_role');
    if (currentUser) localStorage.removeItem(`jwt_${currentUser}`);
    setCurrentUser(null);
    setCurrentRole(null);
    setConvId(null);
    setMessages([]);
    setProfile({ name: '', age: '', country: '', grade: '' });
  };

  // ─── Auth Gate ───────────────────────────────────────────
  if (!currentUser) {
    return <AuthScreen onLogin={(u, r) => { setCurrentUser(u); setCurrentRole(r); }} />;
  }

  // ─── Teacher Layout ──────────────────────────────────────
  if (currentRole === 'teacher') {
    return (
      <>
        <nav className="top-nav">
          <span className="nav-brand">Student Copilot</span>
          <div className="nav-tabs">
            <button className={`nav-tab ${teacherTab === 'upload' ? 'active' : ''}`} onClick={() => setTeacherTab('upload')}>Upload</button>
            <button className={`nav-tab ${teacherTab === 'materials' ? 'active' : ''}`} onClick={() => setTeacherTab('materials')}>Materials</button>
          </div>
          <div className="nav-actions">
            <button className="nav-icon-btn" onClick={() => setSettingsOpen(true)} title="Settings">⚙</button>
            <button className="btn-danger" onClick={handleLogout}>Logout</button>
          </div>
        </nav>
        <div className="content-area">
          <TeacherPortal userId={currentUser} activeTab={teacherTab} />
        </div>
        {settingsOpen && <SettingsModal profile={profile} onClose={() => setSettingsOpen(false)} />}
      </>
    );
  }

  // ─── Student Layout ──────────────────────────────────────
  const isNotebookMode = !!activeSubject.trim();

  return (
    <>
      <nav className="top-nav">
        <span className="nav-brand">Student Copilot</span>
        <div className="nav-tabs">
          <button className={`nav-tab ${tab === 'chat' ? 'active' : ''}`} onClick={() => setTab('chat')}>Chat</button>
          <button className={`nav-tab ${tab === 'revision' ? 'active' : ''}`} onClick={() => setTab('revision')}>Revision</button>
        </div>
        <div className="nav-actions">
          {tab === 'chat' && (
            <button className="btn-ghost" onClick={handleNewChat} style={{ fontSize: '0.78rem', padding: '0.45rem 0.75rem' }}>
              + New Chat
            </button>
          )}
          <button className="nav-icon-btn" onClick={() => setSettingsOpen(true)} title="Settings">⚙</button>
          <button className="btn-danger" onClick={handleLogout}>Logout</button>
        </div>
      </nav>

      <div className="content-area">
        {tab === 'revision' ? (
          <RevisionMode userId={currentUser} />
        ) : (
          <>
            {/* Chat toolbar — subject selector */}
            <div className="chat-toolbar">
              <input
                className="subject-select"
                type="text"
                placeholder="Subject (optional)"
                value={activeSubject}
                onChange={e => setActiveSubject(e.target.value)}
              />
              <span className="chat-mode-label">
                {isNotebookMode
                  ? `Studying ${activeSubject} from your materials`
                  : 'General tutor — ask anything'}
              </span>
            </div>

            {/* Messages */}
            <div className="chat-messages">
              {messages.length === 0 && (
                <div className="chat-empty">
                  <h3>{profile.name ? `Hi ${profile.name.split(' ')[0]}!` : 'Welcome!'}</h3>
                  <p>
                    {isNotebookMode
                      ? `Ask me anything about ${activeSubject}. I'll answer from your study materials.`
                      : 'What would you like to study today? Type a subject above to study from your materials, or just ask me anything.'}
                  </p>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`message ${m.role}`}>
                  {m.role === 'user' ? m.content : (
                    <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
                      {m.content}
                    </ReactMarkdown>
                  )}
                </div>
              ))}
              {loading && (
                <div className="message assistant" style={{ opacity: 0.6 }}>Thinking...</div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input bar */}
            <form className="chat-input-bar" onSubmit={handleSend}>
              <div className="btn-upload-icon" title={uploading ? 'Uploading...' : 'Upload file'}>
                {uploading ? '⏳' : '📎'}
                <input type="file" onChange={handleUpload} disabled={uploading || (!isNotebookMode && !convId)} />
              </div>
              <input
                type="text"
                placeholder="Ask me anything..."
                value={input}
                onChange={e => setInput(e.target.value)}
                disabled={loading || (!isNotebookMode && !convId)}
              />
              <button type="submit" className="btn-send" disabled={loading || !input.trim() || (!isNotebookMode && !convId)}>
                Send
              </button>
            </form>
          </>
        )}
      </div>

      {settingsOpen && <SettingsModal profile={profile} onClose={() => setSettingsOpen(false)} />}

      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.message}
          <button className="toast-close" onClick={() => setToast(null)}>×</button>
        </div>
      )}
    </>
  );
}

// ─── Settings Modal ─────────────────────────────────────────
function SettingsModal({ profile, onClose }: { profile: Profile; onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-body" onClick={e => e.stopPropagation()}>
        <h2>Settings</h2>

        <div className="field">
          <label>Name</label>
          <input type="text" value={profile.name} readOnly />
        </div>
        <div className="field-row">
          <div className="field">
            <label>Age</label>
            <input type="text" value={profile.age || '—'} readOnly />
          </div>
          <div className="field">
            <label>Country</label>
            <input type="text" value={profile.country || '—'} readOnly />
          </div>
        </div>
        <div className="field">
          <label>Class</label>
          <input type="text" value={profile.grade || '—'} readOnly />
        </div>

        {profile.learning_method && (
          <div className="field">
            <label>Identified Learning Style</label>
            <textarea readOnly value={profile.learning_method} rows={4} style={{ opacity: 0.8, resize: 'none' }} />
          </div>
        )}

        <button className="btn-primary" onClick={onClose} style={{ marginTop: '0.5rem' }}>Close</button>
      </div>
    </div>
  );
}

export default App;
