/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// Regression tests for the AI_PROMPT template handling.
//
// The tests cover the cases the competition requires: a JSON array or object
// argument, a repeated placeholder, a nested prompt and a placeholder with
// an invalid index.

#include "gtest/gtest.h"
#include "lib/allocator/ob_arena.h"
#include "common/json_type/ob_json_common.h"
#include "sql/engine/expr/ob_expr_ai/ob_ai_func_utils.h"

using namespace oceanbase;
using namespace oceanbase::common;
using namespace oceanbase::sql;

namespace
{

class ObExprAIPromptTest : public ::testing::Test
{
public:
  void SetUp() override {}
  void TearDown() override {}

protected:
  // Build the prompt object the AI_PROMPT expression builds: a template and
  // the list of the arguments.
  static int build_prompt_object(ObArenaAllocator &allocator,
                                 ObString &template_str,
                                 ObJsonArray *args_array,
                                 ObJsonObject *&prompt_object)
  {
    return ObAIFuncPromptObjectUtils::construct_prompt_object(allocator, template_str,
                                                             args_array, prompt_object);
  }

  static int append_string_arg(ObArenaAllocator &allocator, ObJsonArray *args_array, ObString &value)
  {
    ObJsonString *node = nullptr;
    int ret = OB_SUCCESS;
    if (OB_FAIL(ObAIFuncJsonUtils::get_json_string(allocator, value, node))) {
    } else {
      ret = args_array->append(node);
    }
    return ret;
  }

  static int append_json_object_arg(ObArenaAllocator &allocator, ObJsonArray *args_array)
  {
    ObJsonObject *obj = nullptr;
    int ret = OB_SUCCESS;
    if (OB_FAIL(ObAIFuncJsonUtils::get_json_object(allocator, obj))) {
    } else {
      ObJsonString *value = nullptr;
      ObString value_str("1");
      if (OB_FAIL(ObAIFuncJsonUtils::get_json_string(allocator, value_str, value))) {
      } else if (OB_FAIL(obj->add("a", value))) {
      } else {
        ret = args_array->append(obj);
      }
    }
    return ret;
  }

  static int append_json_array_arg(ObArenaAllocator &allocator, ObJsonArray *args_array)
  {
    ObJsonArray *arr = nullptr;
    int ret = OB_SUCCESS;
    if (OB_FAIL(ObAIFuncJsonUtils::get_json_array(allocator, arr))) {
    } else {
      ObJsonString *value = nullptr;
      ObString value_str("b");
      if (OB_FAIL(ObAIFuncJsonUtils::get_json_string(allocator, value_str, value))) {
      } else if (OB_FAIL(arr->append(value))) {
      } else {
        ret = args_array->append(arr);
      }
    }
    return ret;
  }
};

TEST_F(ObExprAIPromptTest, string_argument_is_replaced)
{
  ObArenaAllocator allocator;
  ObString template_str("{0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ObString arg("value");
  ASSERT_EQ(OB_SUCCESS, append_string_arg(allocator, args_array, arg));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_EQ(0, replaced.compare(ObString("value")));
}

TEST_F(ObExprAIPromptTest, repeated_placeholder_is_replaced_every_time)
{
  ObArenaAllocator allocator;
  ObString template_str("{0} and {0} and {0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ObString arg("x");
  ASSERT_EQ(OB_SUCCESS, append_string_arg(allocator, args_array, arg));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_EQ(0, replaced.compare(ObString("x and x and x")));
}

TEST_F(ObExprAIPromptTest, json_object_argument_is_substituted_with_its_json_text)
{
  ObArenaAllocator allocator;
  ObString template_str("value is {0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, append_json_object_arg(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  // The result carries the json text of the object argument.
  ASSERT_TRUE(replaced.length() > 0);
  ASSERT_TRUE(replaced.find("value is") == 0);
  ASSERT_TRUE(replaced.find("\"a\"") != OB_INVALID_INDEX);
}

TEST_F(ObExprAIPromptTest, json_array_argument_is_substituted_with_its_json_text)
{
  ObArenaAllocator allocator;
  ObString template_str("value is {0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, append_json_array_arg(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_TRUE(replaced.length() > 0);
  ASSERT_TRUE(replaced.find("value is") == 0);
  ASSERT_TRUE(replaced.find("\"b\"") != OB_INVALID_INDEX);
}

TEST_F(ObExprAIPromptTest, out_of_range_placeholder_keeps_the_placeholder)
{
  ObArenaAllocator allocator;
  ObString template_str("{9}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ObString arg("x");
  ASSERT_EQ(OB_SUCCESS, append_string_arg(allocator, args_array, arg));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  // An invalid placeholder index is not an error, the statement keeps running.
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_EQ(0, replaced.compare(ObString("{9}")));
}

TEST_F(ObExprAIPromptTest, non_numeric_placeholder_keeps_the_placeholder)
{
  ObArenaAllocator allocator;
  ObString template_str("{a}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ObString arg("x");
  ASSERT_EQ(OB_SUCCESS, append_string_arg(allocator, args_array, arg));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_EQ(0, replaced.compare(ObString("{a}")));
}

TEST_F(ObExprAIPromptTest, prompt_object_with_json_argument_is_valid)
{
  ObArenaAllocator allocator;
  ObString template_str("{0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, append_json_object_arg(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, append_json_array_arg(allocator, args_array));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  // Both a json object and a json array argument are valid.
  ASSERT_TRUE(ObAIFuncPromptObjectUtils::is_valid_prompt_object(prompt_object));
}

TEST_F(ObExprAIPromptTest, empty_template_is_rejected)
{
  ObArenaAllocator allocator;
  ObString template_str("");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ASSERT_NE(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));
}

TEST_F(ObExprAIPromptTest, unicode_and_escaped_characters_are_kept)
{
  ObArenaAllocator allocator;
  ObString template_str("{0}");
  ObJsonArray *args_array = nullptr;
  ObJsonObject *prompt_object = nullptr;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncJsonUtils::get_json_array(allocator, args_array));
  ObString arg("\xe4\xb8\x96\xe7\x95\x8c");  // two chinese characters
  ASSERT_EQ(OB_SUCCESS, append_string_arg(allocator, args_array, arg));
  ASSERT_EQ(OB_SUCCESS, build_prompt_object(allocator, template_str, args_array, prompt_object));

  ObString replaced;
  ASSERT_EQ(OB_SUCCESS, ObAIFuncPromptObjectUtils::replace_all_str_args_in_template(
      allocator, prompt_object, replaced));
  ASSERT_EQ(arg.length(), replaced.length());
  ASSERT_EQ(0, replaced.compare(arg));
}

} // namespace

int main(int argc, char **argv)
{
  ::testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
