/* 01 - Database and schemas.
   landing   = cleaned files land here, reloaded every run
   core      = the star schema
   audit     = load log
   reporting = views */
IF DB_ID(N'FairfieldLogistics') IS NULL
    CREATE DATABASE FairfieldLogistics;
GO

USE FairfieldLogistics;
GO

IF SCHEMA_ID(N'landing') IS NULL EXEC (N'CREATE SCHEMA landing');
IF SCHEMA_ID(N'core') IS NULL EXEC (N'CREATE SCHEMA core');
IF SCHEMA_ID(N'audit') IS NULL EXEC (N'CREATE SCHEMA audit');
IF SCHEMA_ID(N'reporting') IS NULL EXEC (N'CREATE SCHEMA reporting');
GO
