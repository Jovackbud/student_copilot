```sql
-- schema.sql
-- Run this script in your Supabase SQL Editor to initialize the sovereign context DB.

-- 1. Users Table (Core Identity)
CREATE TABLE IF NOT EXISTS public.users (
    username text PRIMARY KEY,
    password_hash text NOT NULL,
    role text NOT NULL DEFAULT 'student',
    full_name text NOT NULL,
    age integer,
    country text,
    class_id text,
    subjects text,
    learning_method text DEFAULT '',
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Protect against accidental deletion of admin rows (asymmetric protection)
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Enable read access for all" ON public.users FOR SELECT USING (true);
CREATE POLICY "Enable insert for authenticated" ON public.users FOR INSERT WITH CHECK (true);
CREATE POLICY "Enable update for users based on username" ON public.users FOR UPDATE USING ((current_setting('request.jwt.claims', true)::json ->> 'sub')::text = username);

-- 2. Conversations Table (Replaces SESSIONS dict)
CREATE TABLE IF NOT EXISTS public.conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id text NOT NULL REFERENCES public.users(username) ON DELETE CASCADE,
    title text DEFAULT 'Untitled Chat',
    profile_override jsonb DEFAULT '{}'::jsonb,
    summaries jsonb DEFAULT '[]'::jsonb,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Index for fast user conversation lookups
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON public.conversations(user_id);

ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can manage their own conversations" ON public.conversations 
    FOR ALL 
    USING ((current_setting('request.jwt.claims', true)::json ->> 'sub')::text = user_id);

-- Optional: Supabase realtime configuration for future multi-device sync
alter publication supabase_realtime add table public.users;
alter publication supabase_realtime add table public.conversations;
```
