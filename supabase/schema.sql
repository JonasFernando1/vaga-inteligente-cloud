-- Vaga Inteligente: tabelas do Supabase
-- Rode este arquivo inteiro no Supabase: SQL Editor → New query → colar → Run.
-- Pode rodar de novo sempre que ele mudar: não apaga dados.
--
-- Quem acessa o quê:
--   anon (chave pública do dashboard)  → lê vagas, status do sistema e permanências
--   authenticated (usuário logado)     → também lê eventos, último cartão RFID e
--                                        comandos, e CRIA comandos da cancela
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
-- 2. Status do sistema: sinal de vida, cancela e leitor RFID (sem dados pessoais)
-- ---------------------------------------------------------------------------
create table if not exists public.status_sistema (
  id                    int primary key default 1 check (id = 1),
  pi_visto_em           timestamptz,           -- último sinal de vida (hora do servidor)
  api_online            boolean not null default false,
  cancela_aberta        boolean,               -- posição COMANDADA (o SG90 não confirma)
  fechamento_habilitado boolean not null default false
);

alter table public.status_sistema
  add column if not exists rfid_monitor_ativo    boolean,
  add column if not exists rfid_leitor_conectado boolean,
  add column if not exists rfid_ultimo_erro      text,
  add column if not exists auto_estado           text,        -- fechamento RFID de bancada
  add column if not exists auto_modo_bancada     boolean,
  add column if not exists auto_fecha_em         timestamptz; -- quando o fechamento de 10 s dispara

insert into public.status_sistema (id) values (1)
on conflict (id) do nothing;

alter table public.status_sistema enable row level security;

drop policy if exists "todos leem o status" on public.status_sistema;
create policy "todos leem o status" on public.status_sistema
  for select to anon, authenticated using (true);

grant select on public.status_sistema to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Último cartão lido (tem nome da pessoa → só usuário logado)
-- ---------------------------------------------------------------------------
create table if not exists public.status_privado (
  id                  int primary key default 1 check (id = 1),
  rfid_ultima_leitura jsonb,                   -- {nome, status, mensagem, horario}
  atualizado_em       timestamptz not null default now()
);

insert into public.status_privado (id) values (1)
on conflict (id) do nothing;

alter table public.status_privado enable row level security;

drop policy if exists "logados leem o status privado" on public.status_privado;
create policy "logados leem o status privado" on public.status_privado
  for select to authenticated using (true);

revoke all on public.status_privado from anon;
grant select on public.status_privado to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Histórico copiado do SQLite do Raspberry
--    id_local é o id no SQLite; junto com o horário, evita duplicar linhas
--    mesmo se o banco do Pi for recriado e os ids recomeçarem.
-- ---------------------------------------------------------------------------
create table if not exists public.eventos (
  id        bigint generated always as identity primary key,
  id_local  bigint not null,
  horario   timestamptz not null,
  tipo      text not null,                     -- VAGA, RFID, CANCELA
  descricao text not null,
  unique (id_local, horario)
);

create index if not exists eventos_horario on public.eventos (horario desc);

alter table public.eventos enable row level security;

drop policy if exists "logados leem eventos" on public.eventos;
create policy "logados leem eventos" on public.eventos
  for select to authenticated using (true);

revoke all on public.eventos from anon;
grant select on public.eventos to authenticated;

create table if not exists public.permanencias (
  id               bigint generated always as identity primary key,
  id_local         bigint not null,
  vaga_id          int not null,
  entrada          timestamptz not null,
  saida            timestamptz not null,
  duracao_segundos int not null,
  unique (id_local, saida)
);

create index if not exists permanencias_saida on public.permanencias (saida desc);

alter table public.permanencias enable row level security;

drop policy if exists "todos leem permanencias" on public.permanencias;
create policy "todos leem permanencias" on public.permanencias
  for select to anon, authenticated using (true);

grant select on public.permanencias to anon, authenticated;

-- ---------------------------------------------------------------------------
-- 5. Comandos da cancela (dashboard pede, Raspberry executa e responde)
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
-- 6. Funções usadas só pelo Raspberry (chave secreta)
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
-- (A versão antiga, com 3 parâmetros, é substituída por esta.)
drop function if exists public.fn_sinal_de_vida(boolean, boolean, boolean);

create or replace function public.fn_sinal_de_vida(
  p_api_online              boolean,
  p_cancela_aberta          boolean default null,
  p_fechamento_habilitado   boolean default false,
  p_rfid_monitor_ativo      boolean default null,
  p_rfid_leitor_conectado   boolean default null,
  p_rfid_ultimo_erro        text    default null,
  p_auto_estado             text    default null,
  p_auto_modo_bancada       boolean default null,
  p_auto_segundos_restantes numeric default null
)
returns void
language sql
security definer
set search_path = public
as $$
  update status_sistema
     set pi_visto_em           = now(),
         api_online            = p_api_online,
         cancela_aberta        = p_cancela_aberta,
         fechamento_habilitado = coalesce(p_fechamento_habilitado, false),
         rfid_monitor_ativo    = p_rfid_monitor_ativo,
         rfid_leitor_conectado = p_rfid_leitor_conectado,
         rfid_ultimo_erro      = left(p_rfid_ultimo_erro, 500),
         auto_estado           = p_auto_estado,
         auto_modo_bancada     = p_auto_modo_bancada,
         auto_fecha_em         = case
                                   when p_auto_segundos_restantes is null then null
                                   else now() + make_interval(secs => p_auto_segundos_restantes)
                                 end
   where id = 1;
$$;

revoke all on function public.fn_pegar_comando_cancela() from public, anon, authenticated;
revoke all on function public.fn_sinal_de_vida(boolean, boolean, boolean, boolean, boolean, text, text, boolean, numeric)
  from public, anon, authenticated;
grant execute on function public.fn_pegar_comando_cancela() to service_role;
grant execute on function public.fn_sinal_de_vida(boolean, boolean, boolean, boolean, boolean, text, text, boolean, numeric)
  to service_role;
