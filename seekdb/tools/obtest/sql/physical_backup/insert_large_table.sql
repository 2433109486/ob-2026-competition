# Note: 必须是create_large_table.sql或create_non_compress_large_table.sql建的表
# 入参:
# 1. __large_table_name__: 插入的表名
# 3. __start_i__: 插入的行的起始编号
# 3. __count__: 插入的行数

--echo ===============================================================
--echo ================== start insert large table ===================
--echo ===============================================================

--disable_query_log
--disable_result_log

let $__i__ = 0;
while($__i__ < $__count__)
{
  let $__value__ = $__start_i__ + $__i__;
  eval INSERT INTO $__large_table_name__ (pk1, pk2, pk3, f1, f2) VALUES($__value__, $__value__, $__value__, 'abc', REPEAT('1', 262144));
  inc $__i__;
}

--enable_result_log
--enable_query_log

--echo ===============================================================
--echo ================== end insert large table =====================
--echo ===============================================================
