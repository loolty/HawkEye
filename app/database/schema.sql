-- =============================================================
-- Hawkeyes Optical Prescription Management and Appointment
-- Follow-Up System — MySQL 8.x schema (InnoDB / utf8mb4)
--
-- Rules encoded here:
--   * RBAC: users.role ENUM('admin','optometrist','front_desk','patient')
--   * Data privacy: audit_logs records every sensitive CRUD action
--   * Identity: patients.hk_patient_id is the unique online/clinic link key
--   * Optical precision: OD/OS sphere, cylinder, axis, add
-- Idempotent: safe to re-run (CREATE IF NOT EXISTS).
-- =============================================================

CREATE DATABASE IF NOT EXISTS hawkeyes_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE hawkeyes_db;

-- -------------------------------------------------------------
-- USERS (RBAC: admin | optometrist | front_desk | patient)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(120)   NOT NULL,
    email         VARCHAR(180)   NOT NULL,
    password_hash VARCHAR(255)   NOT NULL,          -- pbkdf2_sha256$iters$salt$hash
    role          ENUM('admin','optometrist','front_desk','patient')
                  NOT NULL DEFAULT 'patient',
    is_active     TINYINT(1)     NOT NULL DEFAULT 1,
    created_at    TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_email UNIQUE (email),
    INDEX idx_users_role (role)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- PATIENTS (physical clinic records; hk_patient_id = identity key)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS patients (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    hk_patient_id   VARCHAR(15)  NOT NULL,             -- e.g. 'HK-00001'
    user_id         BIGINT UNSIGNED NULL,             -- linked online account (NULL until signed up)
    first_name      VARCHAR(80)  NOT NULL,
    last_name       VARCHAR(80)  NOT NULL,
    date_of_birth   DATE         NOT NULL,             -- DOB is part of identity resolution
    sex             ENUM('male','female','other') NULL,
    contact_number  VARCHAR(25)  NULL,
    email           VARCHAR(180) NULL,
    address         VARCHAR(255) NULL,
    is_archived     TINYINT(1)   NOT NULL DEFAULT 0,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
                                 ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_patients_hk_patient_id UNIQUE (hk_patient_id),
    CONSTRAINT fk_patients_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE SET NULL ON UPDATE CASCADE,
    -- Identity resolution: match on HK ID + DOB
    INDEX idx_patients_identity (hk_patient_id, date_of_birth),
    INDEX idx_patients_last_name (last_name, first_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- PRESCRIPTIONS (OD = right eye, OS = left eye)
-- DECIMAL(5,2) sphere/cyl/add; axis SMALLINT 0-180 (CHECK)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prescriptions (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    patient_id       BIGINT UNSIGNED NOT NULL,
    optometrist_id   BIGINT UNSIGNED NOT NULL,        -- users.id of issuing optometrist
    exam_date        DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
    od_sphere        DECIMAL(5,2)     NOT NULL,
    od_cylinder      DECIMAL(5,2)     NOT NULL DEFAULT 0.00,
    od_axis          SMALLINT UNSIGNED NULL,          -- 0-180, only with cylinder
    od_add           DECIMAL(5,2)     NULL,           -- near addition (presbyopia)
    os_sphere        DECIMAL(5,2)     NOT NULL,
    os_cylinder      DECIMAL(5,2)     NOT NULL DEFAULT 0.00,
    os_axis          SMALLINT UNSIGNED NULL,
    os_add           DECIMAL(5,2)     NULL,
    pupillary_distance DECIMAL(4,1)   NULL,           -- mm
    lens_type        ENUM('single_vision','bifocal','progressive','reading') NULL,
    notes            TEXT NULL,
    created_by       BIGINT UNSIGNED NOT NULL,        -- users.id (audit trail: who entered it)
    is_archived      TINYINT(1)       NOT NULL DEFAULT 0, -- prescriptions are never hard-deleted
    created_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_rx_patient FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_rx_optometrist FOREIGN KEY (optometrist_id)
        REFERENCES users (id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_rx_created_by FOREIGN KEY (created_by)
        REFERENCES users (id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_rx_axis_od CHECK (od_axis IS NULL OR od_axis BETWEEN 0 AND 180),
    CONSTRAINT chk_rx_axis_os CHECK (os_axis IS NULL OR os_axis BETWEEN 0 AND 180),
    INDEX idx_rx_patient_date (patient_id, exam_date),        -- prescription history
    INDEX idx_rx_optometrist (optometrist_id, exam_date)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- APPOINTMENTS (booking + follow-up tracking)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS appointments (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    patient_id        BIGINT UNSIGNED NOT NULL,
    optometrist_id    BIGINT UNSIGNED NULL,             -- assigned later by front desk
    appointment_date  DATE            NOT NULL,
    start_time        TIME            NOT NULL,
    purpose           VARCHAR(255)    NOT NULL,         -- e.g. 'Eye exam follow-up'
    status            ENUM('pending','confirmed','completed','cancelled','no_show')
                      NOT NULL DEFAULT 'pending',
    source            ENUM('online','walk_in') NOT NULL DEFAULT 'online',
    reminded_at       DATETIME        NULL,             -- set by APScheduler follow-up job
    rescheduled_from  DATE            NULL,             -- original date when moved
    notes             TEXT NULL,
    booked_by         BIGINT UNSIGNED NOT NULL,         -- users.id (patient or staff)
    created_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                      ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_appt_patient FOREIGN KEY (patient_id)
        REFERENCES patients (id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_appt_optometrist FOREIGN KEY (optometrist_id)
        REFERENCES users (id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_appt_booked_by FOREIGN KEY (booked_by)
        REFERENCES users (id) ON DELETE RESTRICT ON UPDATE CASCADE,
    -- no double-booking of the same ophthalmologist at the same time
    CONSTRAINT uq_appt_slot UNIQUE (optometrist_id, appointment_date, start_time),
    INDEX idx_appt_date_status (appointment_date, status),
    INDEX idx_appt_patient (patient_id, appointment_date)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- AUDIT LOGS (Data Privacy rule)
-- Every create/read-bulk/update/delete on `patients` and
-- `prescriptions` inserts one row: who, what, where, when.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id     BIGINT UNSIGNED NULL,     -- NULL for unauthenticated/failed actions
    action      ENUM('CREATE','READ','UPDATE','DELETE','ARCHIVE','LOGIN','LOGOUT',
                     'ACCESS_DENIED') NOT NULL,
    table_name  VARCHAR(64)  NOT NULL,    -- which entity was touched
    record_id   BIGINT UNSIGNED NULL,    -- PK of the affected row
    ip_address  VARCHAR(45)  NULL,       -- IPv4 or IPv6
    details     JSON         NULL,       -- field-level diff / context (no raw secrets)
    timestamp   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    CONSTRAINT fk_audit_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE SET NULL ON UPDATE CASCADE,
    INDEX idx_audit_user_time (user_id, timestamp),
    INDEX idx_audit_table_record (table_name, record_id),
    INDEX idx_audit_action (action, timestamp)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci;
