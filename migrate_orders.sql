-- Migration: add archived flag + created_by_role to orders
-- Run in: supabase.com → your project → SQL Editor

alter table orders add column if not exists archived        boolean default false;
alter table orders add column if not exists created_by_role text    default 'Employee';

-- Server-side delete enforcing role hierarchy
create or replace function delete_order_by_role(order_id uuid)
returns void language plpgsql security definer as $$
declare
  caller_role    text;
  order_owner_id uuid;
  order_role     text;
  caller_lvl     int;
  order_lvl      int;
begin
  select role into caller_role from profiles where id = auth.uid();
  caller_role := coalesce(caller_role, 'Employee');

  select user_id, created_by_role into order_owner_id, order_role
  from orders where id = order_id;

  case caller_role
    when 'Director' then caller_lvl := 4;
    when 'Admin'    then caller_lvl := 4;
    when 'Manager'  then caller_lvl := 3;
    else caller_lvl := 1;
  end case;

  case coalesce(order_role, 'Employee')
    when 'Director' then order_lvl := 4;
    when 'Admin'    then order_lvl := 4;
    when 'Manager'  then order_lvl := 3;
    else order_lvl := 1;
  end case;

  if caller_lvl >= 4 then
    -- Directors / Admins: delete anything
    delete from orders where id = order_id;
  elsif caller_lvl >= 3 then
    -- Managers: delete orders at Manager level or below
    if order_lvl <= 3 then
      delete from orders where id = order_id;
    else
      raise exception 'Managers cannot delete Director or Admin orders.';
    end if;
  else
    -- Employees: only their own orders
    if order_owner_id = auth.uid() then
      delete from orders where id = order_id;
    else
      raise exception 'You can only delete your own orders.';
    end if;
  end if;
end;
$$;

-- Server-side archive (Directors and Admins only)
create or replace function archive_order_by_role(order_id uuid)
returns void language plpgsql security definer as $$
declare
  caller_role text;
  caller_lvl  int;
begin
  select role into caller_role from profiles where id = auth.uid();
  caller_role := coalesce(caller_role, 'Employee');

  case caller_role
    when 'Director' then caller_lvl := 4;
    when 'Admin'    then caller_lvl := 4;
    else caller_lvl := 1;
  end case;

  if caller_lvl < 4 then
    raise exception 'Only Directors and Admins can archive orders.';
  end if;

  update orders set archived = true where id = order_id;
end;
$$;
