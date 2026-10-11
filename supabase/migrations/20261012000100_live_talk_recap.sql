-- "Talk to the recap" (owner, Oct 12 2026): a conversation about the DAY'S RECAP instead of one article.
-- It is counted like any other conversation (same hourly and daily limits, same site-wide cap), as a row of live_sessions with
-- story_id 0. `live_talk_begin` used to answer 'gone' for any story that is not in `published`; story 0 means "the recap", and it
-- is 'gone' only when there is no recap at all (the function live-token has already checked that the day asked for exists).
-- Same arguments as before, so create or replace is enough. Everything else in the function is as in
-- 20261011000400_live_talk_clock_hour.sql.

create or replace function public.live_talk_begin(
  p_reader uuid, p_story integer, p_lang text, p_hourly integer, p_daily integer, p_concurrent integer, p_seconds integer
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  hour_start timestamptz := (date_trunc('hour', now() at time zone 'Asia/Kolkata')) at time zone 'Asia/Kolkata';
  today_start timestamptz := (date_trunc('day', now() at time zone 'Asia/Kolkata')) at time zone 'Asia/Kolkata';
  next_hour timestamptz;
  next_day timestamptz;
  new_id bigint;
  n integer;
begin
  next_hour := hour_start + interval '1 hour';
  next_day := ((date_trunc('day', now() at time zone 'Asia/Kolkata') + interval '1 day')) at time zone 'Asia/Kolkata';
  if p_reader is null then return jsonb_build_object('status', 'login'); end if;
  if p_lang not in ('en', 'hi') or p_hourly < 1 or p_daily < 1 or p_concurrent < 1 or p_seconds < 30 then
    return jsonb_build_object('status', 'bad');
  end if;
  if p_story = 0 then
    if not exists (select 1 from recaps) then
      return jsonb_build_object('status', 'gone');
    end if;
  elsif not exists (select 1 from published where story_id = p_story) then
    return jsonb_build_object('status', 'gone');
  end if;
  perform pg_advisory_xact_lock(7001);
  -- this clock hour (IST): used up until the next XX:00
  if (select count(*) from live_sessions where reader = p_reader and started_at >= hour_start) >= p_hourly then
    return jsonb_build_object('status', 'limit', 'scope', 'hour', 'resets_at', next_hour,
      'retry_minutes', greatest(1, ceil(extract(epoch from (next_hour - now())) / 60)::int));
  end if;
  if (select count(*) from live_sessions where reader = p_reader and started_at >= today_start) >= p_daily then
    return jsonb_build_object('status', 'limit', 'scope', 'day', 'resets_at', next_day,
      'retry_minutes', greatest(1, ceil(extract(epoch from (next_day - now())) / 60)::int));
  end if;
  if (select count(*) from live_sessions where ended_at is null and started_at > now() - make_interval(secs => p_seconds) and last_seen > now() - interval '45 seconds') >= p_concurrent then
    return jsonb_build_object('status', 'busy');
  end if;
  delete from live_sessions where started_at < now() - interval '14 days';
  insert into live_sessions (reader, story_id, lang) values (p_reader, p_story, p_lang) returning id into new_id;
  select count(*) into n from live_sessions where started_at >= today_start;
  return jsonb_build_object('status', 'ok', 'id', new_id, 'n', n);
end $$;
