-- Vaga Inteligente: tabelas do Supabase
-- Rode este arquivo inteiro no Supabase: SQL Editor → New query → colar → Run.
-- Pode rodar de novo sem problema (não apaga dados).
--
-- Quem acessa o quê:
--   anon (chave pública do dashboard)  → só LÊ as vagas e o status do sistema
--   authenticated (usuário logado)     → também lê e CRIA comandos da cancela
--   service_role (chave secreta do Pi) → escreve tudo (ignora RLS)

-- ---------------------------------------------------------------------------
-- 1. Estado das vagas (o Raspberry atualiza; o dashboard lê)
-- ---------------------------------------------------------------------------
create table if not exists public.status_vagas (
  vaga_id       int primary key,
  ocupada       boolean not null default false,
  entrada       timestamptz,                    -- quando o carro entrou (null se livre)
  atualizado_em timestamptz not null default now()
);

insert into public.status_vagas (vaga_id) values (1), (2)
on conflict (vaga_id) do nothing;

alter table public.status_vagas enable row level security;

drop policy if exists "todos leem as vagas" on public.status_vagas;
create policy "todos leem as vagas" on public.status_vagas
  for select to anon, authenticated using (true);

grant select on public.status_vagas to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 2. Status do sistema: sinal de vida do Raspberry e posição da cancela
-- ---------------------------------------------------------------------------
create table if not exists public.status_sistema (
  id                    int primary key default 1 check (id = 1),
  pi_visto_em           timestamptz,           -- último sinal de vida (hora do servidor)
  api_online            boolean not null default false,
  cancela_aberta        boolean,               -- posição COMANDADA (o SG90 não confirma)
  fechamento_habilitado boolean not null default false
);

insert into public.status_sistema (id) values (1)
on conflict (id) do nothing;

alter table public.status_sistema enable row level security;

drop policy if exists "todos leem o status" on public.status_sistema;
create policy "todos leem o status" on public.status_sistema
  for select to anon, authenticated using (true);

grant select on public.status_sistema to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Comandos da cancela (dashboard pede, Raspberry executa e responde)
-- ---------------------------------------------------------------------------
create table if not exists public.comandos_cancela (
  id             bigint generated always as identity primary key,
  acao           text not null check (acao in ('abrir', 'fechar')),
  status         text not null default 'pendente'
                 check (status in ('pendente', 'executando', 'executado',
                                   'recusado', 'expirado', 'erro')),
  mensagem       text,
  solicitado_por uuid default auth.uid() references auth.users (id),
  criado_em      timestamptz not null default now(),
  executado_em   timestamptz
);

create index if not exists comandos_cancela_pendentes
  on public.comandos_cancela (criado_em) where status = 'pendente';

alter table public.comandos_cancela enable row level security;

drop policy if exists "logados leem comandos" on public.comandos_cancela;
create policy "logados leem comandos" on public.comandos_cancela
  for select to authenticated using (true);

-- Usuário logado só cria comando "limpo": pendente, em nome dele, sem resultado.
drop policy if exists "logados criam comandos" on public.comandos_cancela;
create policy "logados criam comandos" on public.comandos_cancela
  for insert to authenticated
  with check (
    status = 'pendente'
    and mensagem is null
    and executado_em is null
    and solicitado_por = auth.uid()
  );

revoke all on public.comandos_cancela from anon;
grant select, insert on public.comandos_cancela to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Funções usadas só pelo Raspberry (chave secreta)
-- ---------------------------------------------------------------------------

-- Pega o próximo comando pendente. Comando com mais de 20 s vira "expirado":
-- assim um clique antigo não move a cancela quando o Pi volta a ter internet.
-- A hora é sempre a do servidor, então o relógio do Pi não interfere.
create or replace function public.fn_pegar_comando_cancela()
returns setof public.comandos_cancela
language plpgsql
security definer
set search_path = public
as $$
begin
  update comandos_cancela
     set status = 'expirado',
         mensagem = 'Não executado: o Raspberry não buscou o comando em 20 s.',
         executado_em = now()
   where status = 'pendente'
     and criado_em < now() - interval '20 seconds';

  -- Comando que ficou "executando" por mais de 1 min (Pi reiniciou no meio).
  update comandos_cancela
     set status = 'erro',
         mensagem = 'Sem resposta do Raspberry.',
         executado_em = now()
   where status = 'executando'
     and criado_em < now() - interval '1 minute';

  return query
  update comandos_cancela
     set status = 'executando'
   where id = (
     select id from comandos_cancela
      where status = 'pendente'
      order by criado_em
      limit 1
      for update skip locked
   )
  returning *;
end;
$$;

-- Sinal de vida do Raspberry, gravado com a hora do servidor.
create or replace function public.fn_sinal_de_vida(
  p_api_online boolean,
  p_cancela_aberta boolean,
  p_fechamento_habilitado boolean
)
returns void
language sql
security definer
set search_path = public
as $$
  update status_sistema
     set pi_visto_em = now(),
         api_online = p_api_online,
         cancela_aberta = p_cancela_aberta,
         fechamento_habilitado = coalesce(p_fechamento_habilitado, false)
   where id = 1;
$$;

revoke all on function public.fn_pegar_comando_cancela() from public, anon, authenticated;
revoke all on function public.fn_sinal_de_vida(boolean, boolean, boolean) from public, anon, authenticated;
grant execute on function public.fn_pegar_comando_cancela() to service_role;
grant execute on function public.fn_sinal_de_vida(boolean, boolean, boolean) to service_role;
