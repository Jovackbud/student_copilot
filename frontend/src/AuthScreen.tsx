import React, { useState } from 'react';
import { API_BASE } from './config';

export const AuthScreen: React.FC<{ onLogin: (userId: string, role: string) => void }> = ({ onLogin }) => {
    const [isLogin, setIsLogin] = useState(true);
    const [role, setRole] = useState<'student' | 'admin'>('student');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // Form Fields
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
            if (isLogin) {
                // LOGIN FLOW
                const res = await fetch(`${API_BASE}/auth/token`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });

                if (!res.ok) {
                    const err = await res.json().catch(() => ({ detail: 'Login Failed' }));
                    throw new Error(err.detail || 'Invalid credentials');
                }

                const data = await res.json();
                localStorage.setItem(`jwt_${data.user_id}`, data.access_token);
                localStorage.setItem('current_user', data.user_id);
                localStorage.setItem('current_role', data.role);
                onLogin(data.user_id, data.role);
            } else {
                // REGISTER FLOW
                const res = await fetch(`${API_BASE}/auth/register`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username,
                        password,
                        role,
                        full_name: fullName,
                        age: age ? parseInt(age) : null,
                        country,
                        class_id: classId,
                        subjects
                    })
                });

                if (!res.ok) {
                    const err = await res.json().catch(() => ({ detail: 'Registration Failed' }));
                    throw new Error(err.detail || 'Failed to register');
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
        <div className="auth-container">
            <div className="auth-card">
                <h1>{isLogin ? 'Sovereign Login' : 'Sovereign Registry'}</h1>
                <p className="subtitle">
                    {isLogin ? 'Enter your credentials.' : 'Initialize your learning context.'}
                </p>

                <div className="mode-toggle" style={{ marginBottom: '2rem' }}>
                    <button 
                        className={role === 'student' ? 'active' : ''} 
                        onClick={() => setRole('student')}
                        type="button"
                    >
                        Student
                    </button>
                    <button 
                        className={role === 'admin' ? 'active' : ''} 
                        onClick={() => setRole('admin')}
                        type="button"
                    >
                        Teacher (Admin)
                    </button>
                </div>

                <form onSubmit={handleSubmit} className="auth-form">
                    <div className="form-group">
                        <label>Username</label>
                        <input required value={username} onChange={e => setUsername(e.target.value)} placeholder="e.g. johndoe" />
                    </div>
                    <div className="form-group">
                        <label>Password</label>
                        <input type="password" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
                    </div>

                    {!isLogin && (
                        <>
                            <div className="form-group">
                                <label>Full Name</label>
                                <input required value={fullName} onChange={e => setFullName(e.target.value)} placeholder="John Doe" />
                            </div>
                            
                            <div className="form-row">
                                <div className="form-group">
                                    <label>Age <span>(Optional)</span></label>
                                    <input type="number" value={age} onChange={e => setAge(e.target.value)} placeholder="16" />
                                </div>
                                <div className="form-group">
                                    <label>Country <span>(Optional)</span></label>
                                    <input value={country} onChange={e => setCountry(e.target.value)} placeholder="Canada" />
                                </div>
                            </div>

                            {role === 'student' && (
                                <>
                                    <div className="form-group">
                                        <label>Class ID</label>
                                        <input value={classId} onChange={e => setClassId(e.target.value)} placeholder="Grade_10" />
                                    </div>
                                    <div className="form-group">
                                        <label>Subjects Enrolled (comma separated)</label>
                                        <input value={subjects} onChange={e => setSubjects(e.target.value)} placeholder="Biology, Math, Physics" />
                                    </div>
                                </>
                            )}
                        </>
                    )}

                    {error && <div className="error-message">{error}</div>}

                    <button type="submit" className="primary auth-submit" style={{ width: '100%', marginTop: '1rem', padding: '1rem' }} disabled={loading}>
                        {loading ? 'Processing...' : (isLogin ? 'Authenticate' : 'Establish Context')}
                    </button>
                </form>

                <p className="toggle-mode">
                    {isLogin ? "Don't have a profile? " : "Already established? "}
                    <button className="text-btn" onClick={() => setIsLogin(!isLogin)}>
                        {isLogin ? 'Register Here.' : 'Login Here.'}
                    </button>
                </p>
            </div>
        </div>
    );
};
