-- SQLcl login configuration
-- This file is automatically loaded when SQLcl starts

-- Enable command history
set history on

-- Show query execution time
set timing on

-- Better output formatting
set sqlformat ansiconsole
set pagesize 100
set linesize 200

-- Trim trailing spaces
set trimspool on
set tab off

-- Custom prompt showing user and connection
set sqlprompt "_user'@'_connect_identifier > "

-- Disable autocommit for safety
set autocommit off

-- Made with Bob
