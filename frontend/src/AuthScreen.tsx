import React, { useState } from 'react';
import { API_BASE } from './config';

interface AuthProps {
  onLogin: (userId: string, role: string) => void;
}

export const AuthScreen: React.FC<AuthProps> = ({ onLogin }) => {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [role, setRole] = useState<'student' | 'teacher'>('student');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [age, setAge] = useState('');
  const [country, setCountry] = useState('');
  const [classId, setClassId] = useState('');
  const [subjects, setSubjects] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (mode === 'login') {
        const res = await fetch(`${API_BASE}/auth/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Login failed' }));
          throw new Error(err.detail || 'Invalid credentials');
        }
        const data = await res.json();
        localStorage.setItem(`jwt_${data.user_id}`, data.access_token);
        localStorage.setItem('current_user', data.user_id);
        localStorage.setItem('current_role', data.role);
        onLogin(data.user_id, data.role);
      } else {
        const res = await fetch(`${API_BASE}/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username, password, role,
            full_name: fullName,
            age: age ? parseInt(age) : null,
            country, class_id: classId, subjects
          })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
          throw new Error(err.detail || 'Failed to create account');
        }
        const data = await res.json();
        localStorage.setItem(`jwt_${data.user_id}`, data.access_token);
        localStorage.setItem('current_user', data.user_id);
        localStorage.setItem('current_role', data.role);
        onLogin(data.user_id, data.role);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>Student Copilot</h1>
        <p className="subtitle">Your AI-powered study partner</p>

        <div className="auth-tabs">
          <button className={`auth-tab ${mode === 'login' ? 'active' : ''}`} onClick={() => setMode('login')} type="button">
            Sign In
          </button>
          <button className={`auth-tab ${mode === 'register' ? 'active' : ''}`} onClick={() => setMode('register')} type="button">
            Create Account
          </button>
        </div>

        {mode === 'register' && (
          <div className="role-toggle">
            <button className={`role-btn ${role === 'student' ? 'active' : ''}`} onClick={() => setRole('student')} type="button">
              Student
            </button>
            <button className={`role-btn ${role === 'teacher' ? 'active' : ''}`} onClick={() => setRole('teacher')} type="button">
              Teacher
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="field">
            <label>Username</label>
            <input type="text" required value={username} onChange={e => setUsername(e.target.value)} placeholder="e.g. johndoe" />
          </div>
          <div className="field">
            <label>Password</label>
            <input type="password" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
          </div>

          {mode === 'register' && (
            <>
              <div className="field">
                <label>Full Name</label>
                <input type="text" required value={fullName} onChange={e => setFullName(e.target.value)} placeholder="John Doe" />
              </div>
              <div className="field-row">
                <div className="field">
                  <label>Age <span className="optional">(optional)</span></label>
                  <input type="number" value={age} onChange={e => setAge(e.target.value)} placeholder="16" />
                </div>
                <div className="field">
                  <label>Country <span className="optional">(optional)</span></label>
                  <input type="text" value={country} onChange={e => setCountry(e.target.value)} placeholder="Nigeria" />
                </div>
              </div>
              {role === 'student' && (
                <>
                  <div className="field">
                    <label>Class ID</label>
                    <input type="text" value={classId} onChange={e => setClassId(e.target.value)} placeholder="e.g. SSS 1" />
                  </div>
                  <div className="field">
                    <label>Subjects <span className="optional">(comma separated)</span></label>
                    <input type="text" value={subjects} onChange={e => setSubjects(e.target.value)} placeholder="Biology, Math, Physics" />
                  </div>
                </>
              )}
            </>
          )}

          {error && <div className="field-error">{error}</div>}

          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : (mode === 'login' ? 'Sign In' : 'Create Account')}
          </button>
        </form>
      </div>
    </div>
  );
};
