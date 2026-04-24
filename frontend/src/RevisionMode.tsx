import React, { useState } from 'react';
import { API_BASE, authHeaders } from './config';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

interface Question {
  id: string;
  type: 'mcq' | 'theory';
  text: string;
  options?: string[];
  correct_answer?: string;
}

interface RevisionModeProps {
  userId: string;
}

export const RevisionMode: React.FC<RevisionModeProps> = ({ userId }) => {
  const [step, setStep] = useState<'config' | 'exam' | 'result'>('config');
  const [config, setConfig] = useState({ classId: '', subject: '', topics: '', mcqCount: 5, theoryCount: 2 });
  const [questions, setQuestions] = useState<Question[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  const resetSession = () => {
    setStep('config');
    setQuestions([]);
    setAnswers({});
    setFeedback('');
    setError('');
  };

  const handleCountChange = (field: 'mcqCount' | 'theoryCount', value: string) => {
    const parsed = parseInt(value);
    const clamped = isNaN(parsed) ? 0 : Math.max(0, Math.min(20, parsed));
    setConfig({ ...config, [field]: clamped });
  };

  const startExam = async () => {
    if (!config.subject.trim()) return setError('Please enter a subject.');
    if (!config.classId.trim()) return setError('Please enter your class.');
    if (config.mcqCount + config.theoryCount === 0) return setError('Set at least 1 question.');
    setLoading(true);
    setError('');
    try {
      const headers = await authHeaders(userId);
      const res = await fetch(`${API_BASE}/revision/generate`, {
        method: 'POST', headers,
        body: JSON.stringify({
          class_id: config.classId, subject: config.subject,
          topics: config.topics || undefined,
          mcq_count: config.mcqCount, theory_count: config.theoryCount
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const qs = data.questions || [];
      if (qs.length === 0) throw new Error('No questions generated. Ask your teacher to upload materials first.');
      setQuestions(qs);
      setAnswers({});
      setStep('exam');
    } catch (err: any) {
      setError(err.message || 'Failed to generate exam.');
    } finally {
      setLoading(false);
    }
  };

  const submitExam = async () => {
    const answered = Object.keys(answers).filter(k => answers[k].trim()).length;
    if (answered === 0) return setError('Please answer at least one question.');
    setLoading(true);
    setError('');
    try {
      const headers = await authHeaders(userId);
      const res = await fetch(`${API_BASE}/revision/evaluate`, {
        method: 'POST', headers,
        body: JSON.stringify({
          class_id: config.classId, subject: config.subject,
          questions, answers
        })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setFeedback(data.feedback);
      setStep('result');
    } catch (err: any) {
      setError(err.message || 'Grading failed.');
    } finally {
      setLoading(false);
    }
  };

  if (step === 'config') {
    return (
      <div className="revision-view">
        <div className="revision-header">
          <h2>Revision & Practice</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem' }}>
            Generate a personalized exam from your teacher's materials.
          </p>
        </div>
        {error && <div className="field-error" style={{ maxWidth: 600, margin: '0 auto 1rem' }}>{error}</div>}
        <div className="revision-form">
          <div className="field">
            <label>Class</label>
            <input type="text" value={config.classId} onChange={e => setConfig({...config, classId: e.target.value})} placeholder="e.g. SSS 1" />
          </div>
          <div className="field">
            <label>Subject</label>
            <input type="text" value={config.subject} onChange={e => setConfig({...config, subject: e.target.value})} placeholder="e.g. Biology" />
          </div>
          <div className="field">
            <label>Specific Topics <span className="optional">(optional)</span></label>
            <input type="text" value={config.topics} onChange={e => setConfig({...config, topics: e.target.value})} placeholder="e.g. Cell Division, Mitosis" />
          </div>
          <div className="field-row">
            <div className="field">
              <label>Multiple Choice</label>
              <input type="number" min="0" max="20" value={config.mcqCount} onChange={e => handleCountChange('mcqCount', e.target.value)} />
            </div>
            <div className="field">
              <label>Theory Questions</label>
              <input type="number" min="0" max="20" value={config.theoryCount} onChange={e => handleCountChange('theoryCount', e.target.value)} />
            </div>
          </div>
          <button onClick={startExam} className="btn-primary" disabled={loading}>
            {loading ? 'Preparing your exam...' : 'Generate Exam'}
          </button>
        </div>
      </div>
    );
  }

  if (step === 'exam') {
    return (
      <div className="revision-view">
        <div className="revision-header">
          <h2>Exam: {config.subject}</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            {questions.length} questions • {Object.keys(answers).filter(k => answers[k]?.trim()).length} answered
          </p>
        </div>
        {error && <div className="field-error" style={{ maxWidth: 700, margin: '0 auto 1rem' }}>{error}</div>}
        <div className="questions-list">
          {questions.map((q, idx) => (
            <div key={q.id} className="question-card">
              <span className="q-badge">{q.type.toUpperCase()}</span>
              <p className="q-text">{idx + 1}. {q.text}</p>
              {q.type === 'mcq' ? (
                <div className="options-grid">
                  {q.options?.map(opt => (
                    <label key={opt} className={`option-label ${answers[q.id] === opt ? 'active' : ''}`}>
                      <input type="radio" name={q.id} value={opt} checked={answers[q.id] === opt}
                        onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} />
                      {opt}
                    </label>
                  ))}
                </div>
              ) : (
                <textarea placeholder="Write your answer..." value={answers[q.id] || ''}
                  onChange={e => setAnswers({ ...answers, [q.id]: e.target.value })} rows={4} />
              )}
            </div>
          ))}
        </div>
        <div className="revision-actions">
          <button onClick={submitExam} className="btn-primary" disabled={loading}>
            {loading ? 'Grading...' : 'Submit for Grading'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="revision-view">
      <div className="revision-header">
        <h2>Your Results</h2>
      </div>
      <div className="feedback-block">
        {feedback && (
          <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}>
            {feedback}
          </ReactMarkdown>
        )}
      </div>
      <div className="revision-actions">
        <button onClick={resetSession} className="btn-ghost" style={{ width: '100%' }}>
          Start New Exam
        </button>
      </div>
    </div>
  );
};
