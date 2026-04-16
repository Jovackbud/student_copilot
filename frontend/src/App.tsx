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
  [key: string]: any;
}

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

function App() {
  const [currentUser, setCurrentUser] = useState<string | null>(localStorage.getItem('current_user'));
  const [currentRole, setCurrentRole] = useState<string | null>(localStorage.getItem('current_role'));

  const [profile, setProfile] = useState<Profile>({ name: '', age: '', country: '', grade: '' });
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  
  const [mode, setMode] = useState<'general' | 'notebook' | 'revision'>('general');
  const [activeSubject, setActiveSubject] = useState('');
  const [view, setView] = useState<'student' | 'teacher'>('student');

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Load Profile from backend config upon login
  useEffect(() => {
    async function loadProfile() {
      if (!currentUser) return;
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
          if (data.role === 'admin') setView('teacher');
        }
      } catch (err) {
        console.error("Failed to load profile", err);
      }
    }
    loadProfile();
  }, [currentUser]);

  // Init conversation — skip for notebook AND revision modes
  useEffect(() => {
    async function init() {
      if (!currentUser || mode !== 'general') return;
      if (convId && !convId.startsWith('notebook_temp_')) return;
      try {
        const headers = await authHeaders(currentUser);
        const res = await fetch(`${API_BASE}/conversations/new`, {
          method: 'POST',
          headers: headers,
          body: JSON.stringify({ initial_message: 'Hello' })
        });
        checkAuthExpiry(res);
        const data = await res.json();
        setConvId(data.conversation_id);
      } catch (err) {
        console.error("Failed to init conversation:", err);
      }
    }
    init();
  }, [mode, currentUser]);

  const handleProfileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setProfile({ ...profile, [e.target.name]: e.target.value });
  };

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!input.trim()) return;
    // General mode requires a conversation_id; notebook mode does not
    if (mode === 'general' && !convId) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setLoading(true);

    try {
      const endpoint = mode === 'general' ? `${API_BASE}/chat` : `${API_BASE}/notebook/ask`;
      const bodyPayload = mode === 'general' 
        ? {
            conversation_id: convId,
            message: userMsg,
            user_profile: {
              full_name: profile.name,
              age: profile.age,
              country: profile.country,
              class_id: profile.grade
            }
          }
        : {
            question: userMsg,
            active_subject: activeSubject,
            active_class: profile.grade
          };

      const headers = await authHeaders(currentUser!);
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(bodyPayload)
      });
      
      checkAuthExpiry(res);
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(errorData.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.reply || data.answer }]);
    } catch (err: any) {
      console.error(err);
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.message || 'Could not reach the server.'}` }]);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0]) return;
    // General upload requires convId (query param); notebook upload does not
    if (mode === 'general' && !convId) return;
    const selectedFile = e.target.files[0];
    setUploading(true);

    const formData = new FormData();
    formData.append('file', selectedFile);
    if (mode === 'notebook') {
      formData.append('subject', activeSubject || 'General');
      formData.append('class_id', profile.grade || 'General');
    }

    try {
      const uploadEndpoint = mode === 'general' 
        ? `${API_BASE}/upload?conversation_id=${convId}` 
        : `${API_BASE}/notebook/upload`;

      const headers = await authHeadersMultipart(currentUser!);
      const res = await fetch(uploadEndpoint, {
        method: 'POST',
        headers: headers,
        body: formData
      });
      checkAuthExpiry(res);
      const data = await res.json();
      if (mode === 'notebook' && data.session_id) {
         setConvId(data.session_id);
         alert(`Notebook Context uploaded. Extracted ${data.chunks} vector chunks.`);
      } else {
         alert(`Upload complete: \n${data.summary?.substring(0, 50)}...`);
      }
    } catch (err) {
      console.error(err);
      alert('Upload failed.');
    } finally {
      setUploading(false);
    }
  };

  const handleEndSession = async () => {
    if (!convId || mode !== 'general') return;
    setLoading(true);
    try {
      const headers = await authHeaders(currentUser!);
      const res = await fetch(`${API_BASE}/conversations/${convId}/end`, {
        method: 'POST',
        headers: headers
      });
      const data = await res.json();
      if (data.learning_method) {
        setProfile(prev => ({ ...prev, learning_method: data.learning_method }));
        alert(`Session ended. Permanent Learning Methodology:\n\n${data.learning_method}`);
      }
      // Reset state without full page reload (M1 fix)
      setMessages([]);
      setConvId(null);
      setInput('');
      // Auto-create a new conversation for seamless UX
      try {
        const newHeaders = await authHeaders(currentUser!);
        const newConvRes = await fetch(`${API_BASE}/conversations/new`, {
          method: 'POST',
          headers: newHeaders,
          body: JSON.stringify({})
        });
        const newConvData = await newConvRes.json();
        if (newConvData.conversation_id) setConvId(newConvData.conversation_id);
      } catch (convErr) {
        console.error('Failed to create new conversation after session end', convErr);
      }
    } catch (err) {
      console.error(err);
      alert('Failed to end session properly.');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('current_user');
    localStorage.removeItem('current_role');
    if (currentUser) localStorage.removeItem(`jwt_${currentUser}`);
    setCurrentUser(null);
    setCurrentRole(null);
    setConvId(null);
    setMessages([]);
    setProfile({ name: '', age: '', country: '', grade: '' });
  };

  if (!currentUser) {
    return <AuthScreen onLogin={(u, r) => { setCurrentUser(u); setCurrentRole(r); }} />;
  }

  if (view === 'teacher') {
    return (
      <div style={{ width: '100%', height: '100%', overflow: 'auto' }}>
        <div style={{ position: 'fixed', top: '1rem', right: '1rem', zIndex: 100, display: 'flex', gap: '1rem' }}>
          <button onClick={() => setView('student')} style={{ background: 'var(--border)', color: 'var(--text)' }}>Back to App</button>
          <button onClick={handleLogout} style={{ background: '#ef4444', color: 'white' }}>Logout</button>
        </div>
        <TeacherPortal userId={currentUser!} />
      </div>
    );
  }

  return (
    <div className="app-container">
      <div className="sidebar">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2>{mode === 'general' ? 'Sovereign Tutor' : mode === 'notebook' ? 'Notebook Oracle' : 'Revision Hub'}</h2>
          <div style={{ display: 'flex', gap: '0.4rem' }}>
            {currentRole === 'admin' && (
              <button onClick={() => setView('teacher')} style={{ padding: '0.3rem 0.6rem', fontSize: '0.7rem', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-dim)' }}>Admin</button>
            )}
            <button onClick={handleLogout} style={{ padding: '0.3rem 0.6rem', fontSize: '0.7rem', background: '#ef4444', border: 'none', color: 'white' }}>Exit</button>
          </div>
        </div>
        
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
          <button 
            style={{ flex: 1, padding: '0.5rem', opacity: mode === 'general' ? 1 : 0.5, border: mode === 'general' ? '1px solid var(--accent)' : 'none' }}
            onClick={() => setMode('general')}
          >
            Tutor
          </button>
          <button 
            style={{ flex: 1, padding: '0.5rem', opacity: mode === 'notebook' ? 1 : 0.5, border: mode === 'notebook' ? '1px solid var(--accent)' : 'none' }}
            onClick={() => { setMode('notebook'); setMessages([]); setConvId('notebook_temp_' + Date.now()); }}
          >
            Notebook
          </button>
          <button 
            style={{ flex: 1, padding: '0.5rem', opacity: mode === 'revision' ? 1 : 0.5, border: mode === 'revision' ? '1px solid var(--accent)' : 'none' }}
            onClick={() => setMode('revision')}
          >
            Revision
          </button>
        </div>

        <p style={{ fontSize: '0.8rem', color: 'var(--text-dim)' }}>
          {mode === 'general' 
            ? 'Longitudinal AI. Adapts to your learning style across sessions.' 
            : mode === 'notebook' 
            ? 'Ground truth retrieval. Answers strictly from context.'
            : 'Socratic Assessment. Personalized exams from textbooks.'}
        </p>

        {(mode === 'notebook' || mode === 'revision') && (
          <div className="form-group">
            <label>Active Subject</label>
            <input 
              placeholder="e.g. Biology" 
              value={activeSubject} 
              onChange={e => setActiveSubject(e.target.value)} 
            />
          </div>
        )}
        
        <div className="form-group">
          <label>Name</label>
          <input name="name" type="text" value={profile.name} onChange={handleProfileChange} disabled={mode !== 'general'}/>
        </div>
        <div className="form-group">
          <label>Age</label>
          <input name="age" type="text" value={profile.age} onChange={handleProfileChange} disabled={mode !== 'general'}/>
        </div>
        <div className="form-group">
          <label>Country</label>
          <input name="country" type="text" value={profile.country} onChange={handleProfileChange} disabled={mode !== 'general'}/>
        </div>
        <div className="form-group">
          <label>Education Grade</label>
          <input name="grade" type="text" value={profile.grade} onChange={handleProfileChange} disabled={mode !== 'general'}/>
        </div>
        
        {mode !== 'revision' && (
          <div className="form-group" style={{ marginTop: 'auto' }}>
            <label>Context Upload</label>
            <input type="file" onChange={handleUpload} disabled={uploading || (mode === 'general' && !convId)} style={{ background: 'transparent', padding: '0.5rem 0' }} />
            {uploading && <span style={{ fontSize: '0.8rem', color: 'var(--accent)' }}>Processing & Vectorizing...</span>}
          </div>
        )}

        {mode === 'general' && (
          <button 
            onClick={handleEndSession} 
            disabled={loading || !convId}
            style={{ marginTop: '1rem', background: 'var(--border)', color: 'var(--text)' }}
          >
            End Session & Analyze Profile
          </button>
        )}
      </div>

      <div className="main-chat">
          {mode === 'revision' ? (
              <RevisionMode userId={currentUser!} />
          ) : (
            <div className="chat-messages">
              {messages.length === 0 && (
                <div style={{ margin: 'auto', textAlign: 'center', color: 'var(--text-dim)' }}>
                  <h3>student_copilot OS Ready</h3>
                  <p>Configure profile left. Upload context. Chat below.</p>
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`message ${m.role}`}>
                  {m.role === 'user' ? (
                    m.content
                  ) : (
                    <ReactMarkdown
                      remarkPlugins={[remarkMath, remarkGfm]}
                      rehypePlugins={[rehypeKatex]}
                    >
                      {m.content}
                    </ReactMarkdown>
                  )}
                </div>
              ))}
              {loading && (
                <div className="message assistant" style={{ opacity: 0.7 }}>
                  Reasoning...
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        
        {mode !== 'revision' && (
          <form className="chat-input-area" onSubmit={handleSend}>
            <input
              type="text"
              placeholder="Query the sovereign context..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading || (mode === 'general' && !convId)}
            />
            <button type="submit" disabled={loading || !input.trim() || (mode === 'general' && !convId)}>Send</button>
          </form>
        )}
      </div>
    </div>
  );
}

export default App;
