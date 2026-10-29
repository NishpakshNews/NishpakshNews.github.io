-- Clear notifications and the reader's audio list (owner, Oct 29 2026).
-- "Clear" is a soft clear (cleared_at), not a delete: notifications are unique per (reader, kind, ref) and the
-- audio quota counts audio_requests per IST day, so deleting a row would let the same notice come again or give a
-- second request in a day. A cleared row is only hidden from the reader's own lists.
alter table public.notifications add column if not exists cleared_at timestamptz;
alter table public.audio_requests add column if not exists cleared_at timestamptz;

grant update (read_at, cleared_at) on public.notifications to authenticated;
grant update (cleared_at) on public.audio_requests to authenticated;

drop policy if exists own_audio_clear on public.audio_requests;
create policy own_audio_clear on public.audio_requests for update to authenticated
  using (reader = auth.uid()) with check (reader = auth.uid());

-- asking again for an audio that was cleared (or whose file expired) shows it in the list again
create or replace function public.request_audio(p_story integer, p_lang text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  me uuid := auth.uid();
  f record;
  today_start timestamptz := (date_trunc('day', now() at time zone 'Asia/Kolkata')) at time zone 'Asia/Kolkata';
begin
  if me is null then return jsonb_build_object('status', 'login'); end if;
  if p_lang not in ('en', 'hi') then return jsonb_build_object('status', 'bad'); end if;
  if not exists (select 1 from published where story_id = p_story) then return jsonb_build_object('status', 'gone'); end if;
  select * into f from audio_files where key = p_story || '-' || p_lang;
  if found then return jsonb_build_object('status', 'ready', 'url', f.url); end if;
  if exists (select 1 from audio_requests where reader = me and story_id = p_story and lang = p_lang and status = 'queued') then
    return jsonb_build_object('status', 'queued');
  end if;
  if (select count(*) from audio_requests where reader = me and requested_at >= today_start) >= 1 then
    return jsonb_build_object('status', 'limit');
  end if;
  insert into audio_requests (reader, story_id, lang) values (me, p_story, p_lang)
    on conflict (reader, story_id, lang) do update set status = 'queued', requested_at = now(), done_at = null, cleared_at = null;
  return jsonb_build_object('status', 'queued');
end $$;
revoke all on function public.request_audio(integer, text) from public, anon;
grant execute on function public.request_audio(integer, text) to authenticated;
