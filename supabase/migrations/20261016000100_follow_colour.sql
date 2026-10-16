-- Colour notifications (owner, Oct 16 2026): a reader may be told when lines of a live article turn established,
-- developing, disputed or false (notify.queue_colours, at most one notification per article per hour). A follow of
-- kind 'colour' whose key is the colour.
alter table public.follows drop constraint if exists follows_kind_check;
alter table public.follows add constraint follows_kind_check
  check (kind in ('section', 'place', 'entity', 'story', 'recap', 'next', 'colour'));
